"""实践 TAB 的运行环境：本机（CPU / Apple GPU）和阿里云 GPU（用时才开机，空闲或到花费上限自动释放）。

两种运行环境都是「一个 Jupyter Server + 课程工作目录」：
- 本机：data/practice/venv（uv 建，锁 torch 2.5.1——新版在 macOS 14 的 MPS 上会崩），jupyter server 绑 127.0.0.1。
- 阿里云：aliyun CLI（settings practice.cloud.profile）开 A10 抢占式实例，预装驱动 + CUDA 的 Ubuntu 镜像；
  RunInstances 带 AutoReleaseTime 兜底（平台挂了也会到点释放）；SSH 隧道把远端 8888 映射到本机端口，
  反向隧道把平台端口给云端，课程里 ss.llm() 一样能用本机 Claude。
课程依赖按 course.json 懒安装（每门课一个标记文件），仓库由平台在本机 clone 一份再打包上传，不依赖云上访问 GitHub。
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tarfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from .. import db, settings
from . import _practice_kernel as K

log = logging.getLogger(__name__)

ROOT = db.DATA_DIR / "practice"
SRC = ROOT / "src"
ASSETS = Path(__file__).resolve().parent.parent.parent / "practice"
LOCAL_TORCH = "torch==2.5.1"
BASE_PKGS = ["ipykernel", "jupyter_server", "numpy", "httpx"]
NO_PROXY = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy")

CLOUD_DEFAULTS = {"profile": "default", "region": "cn-hangzhou", "zones": ["cn-hangzhou-k", "cn-hangzhou-j"],
                  "instance_type": "ecs.gn7i-c8g1.2xlarge", "image_like": "ubuntu_22_04_x64_100G_with_gpu_driver_and_cuda",
                  "cap_yuan": 20, "idle_min": 30, "disk_yuan_h": 0.15, "vsw_cidr": "172.16.9.0/24"}


def cfg() -> dict:
    return {**CLOUD_DEFAULTS, **(settings.get("practice.cloud", {}) or {})}


def platform_port() -> int:
    return int(os.environ.get("PORT") or 8780)


# ---------- 状态（practice_runtime 一行一个运行环境：local / cloud） ----------

def state(kind: str) -> dict:
    r = db.row("SELECT * FROM practice_runtime WHERE kind=?", [kind])
    if not r:
        db.execute("INSERT INTO practice_runtime (kind, status) VALUES (?, 'stopped')", [kind])
        r = db.row("SELECT * FROM practice_runtime WHERE kind=?", [kind])
    r["info"] = json.loads(r.get("info") or "{}")
    return r


def _set(kind: str, **kw) -> None:
    if "info" in kw:
        kw["info"] = json.dumps(kw["info"], ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in kw)
    db.execute(f"UPDATE practice_runtime SET {sets} WHERE kind=?", [*kw.values(), kind])


def _log(kind: str, line: str) -> None:
    r = db.row("SELECT log FROM practice_runtime WHERE kind=?", [kind]) or {"log": ""}
    text = ((r["log"] or "") + time.strftime("%H:%M:%S ") + line.rstrip() + "\n")[-20000:]
    db.execute("UPDATE practice_runtime SET log=? WHERE kind=?", [text, kind])


def touch(kind: str) -> None:
    db.execute("UPDATE practice_runtime SET last_active=? WHERE kind=?", [time.time(), kind])


def cost(r: dict) -> float:
    if not r.get("started_at"):
        return 0.0
    end = r.get("stopped_at") if r["status"] in ("stopped", "failed") and r.get("stopped_at") else time.time()
    return round(max(0.0, end - r["started_at"]) / 3600 * (r.get("price") or 0), 2)


def view(kind: str) -> dict:
    r = state(kind)
    out = {k: r.get(k) for k in ("kind", "status", "price", "cap", "started_at", "ready_at", "last_active", "error")}
    out.update(cost=cost(r), log=(r.get("log") or "")[-3000:], courses=[x.split("@")[0] for x in r["info"].get("courses", [])],
               ip=r["info"].get("ip", ""), zone=r["info"].get("zone", ""), busy=len(K.running()),
               idle_min=cfg()["idle_min"] if kind == "cloud" else 0)
    return out


def server(kind: str) -> K.Server | None:
    r = state(kind)
    if r["status"] != "ready":
        return None
    return K.Server(f"http://127.0.0.1:{r['port']}", r["token"])


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _run(cmd: list[str], timeout: int = 600, env=None, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)


def _env_noproxy() -> dict:
    return {k: v for k, v in os.environ.items() if k not in NO_PROXY}


# ---------- 课程源码：平台在本机 clone，一份给本机用、一份打包给云 ----------

PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ]*$")


def pip_pkgs(course: dict, skip_torch: bool = False) -> list[str]:
    pkgs = [x for x in course.get("pip", []) if not (skip_torch and x.startswith("torch"))]
    bad = [x for x in pkgs if not PKG_RE.match(x)]
    if bad:
        raise RuntimeError(f"course.json 的 pip 里有不合法的包名：{bad}")
    return pkgs


def course_src(course: dict) -> Path | None:
    repo = course.get("repo")
    if not repo:
        return None
    url = repo["url"] if isinstance(repo, dict) else repo
    if not url.startswith("https://"):
        raise RuntimeError("课程仓库只接受 https:// 地址")
    dst = SRC / course["id"]
    if not (dst / ".git").exists():
        SRC.mkdir(parents=True, exist_ok=True)
        r = _run(["git", "clone", "--depth", "1", *(["--branch", course["ref"]] if course.get("ref") else []), "--", url, str(dst)], timeout=900)
        if r.returncode:
            raise RuntimeError("拉取课程仓库失败：" + (r.stderr or r.stdout)[-400:])
    return dst


def bundle(course: dict) -> Path:
    """课程仓库代码 + 平台的 ss.py 打成 tar.gz；本机下的数据集 / 权重 / 图片不传（云上自己从 ModelScope 下，走内网更快）。"""
    src = course_src(course)
    out = ROOT / f"bundle-{course['id']}.tar.gz"
    skip = set(course.get("bundle_skip", ["images", ".git", "out", "checkpoints"]))
    with tarfile.open(out, "w:gz") as tf:
        if src:
            for p in src.iterdir():
                if p.name in skip:
                    continue
                tf.add(p, arcname=f"{course['id']}/{p.name}", filter=lambda ti: None if ti.isfile() and ti.size > 5_000_000 else ti)
        tf.add(ASSETS / "ss.py", arcname="ss.py")
        for f in sorted((Path(course["dir"]) / "lib").glob("*.py")) if course.get("dir") else []:
            tf.add(f, arcname=f.name)
    return out


# ---------- 运行器接口：sh(cmd) 在运行环境里跑 shell；put(local, remote) 传文件 ----------

class Local:
    kind = "local"

    def __init__(self):
        self.work = ROOT / "work"
        self.venv = ROOT / "venv"

    def py(self) -> str:
        return str(self.venv / "bin" / "python")

    def sh(self, cmd: str, timeout: int = 1800) -> tuple[int, str]:
        self.work.mkdir(parents=True, exist_ok=True)
        r = _run(["bash", "-lc", cmd], timeout=timeout, cwd=str(self.work))
        return r.returncode, (r.stdout + r.stderr)[-4000:]

    def boot(self, say) -> dict:
        uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
        if not (self.venv / "bin" / "python").exists():
            say("创建本机 Python 环境（首次约 1–2 分钟）")
            r = _run([uv, "venv", "--python", "3.11", str(self.venv)], timeout=600)
            if r.returncode:
                raise RuntimeError(r.stderr[-400:])
            r = _run([uv, "pip", "install", "--python", self.py(), *BASE_PKGS, LOCAL_TORCH], timeout=1800)
            if r.returncode:
                raise RuntimeError("装基础依赖失败：" + r.stderr[-400:])
        self.work.mkdir(parents=True, exist_ok=True)
        shutil.copy(ASSETS / "ss.py", self.work / "ss.py")
        port, token = _free_port(), secrets.token_hex(16)
        env = {**os.environ, "SS_PLATFORM": f"http://127.0.0.1:{platform_port()}", "SS_RUNTIME": "local", "SS_WORK": str(self.work),
               "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        logf = open(ROOT / "jupyter-local.log", "ab")
        p = subprocess.Popen([str(self.venv / "bin" / "jupyter"), "server", "--no-browser", f"--port={port}", "--ip=127.0.0.1",
                              f"--IdentityProvider.token={token}", f"--ServerApp.root_dir={self.work}"],
                             stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        s = K.Server(f"http://127.0.0.1:{port}", token)
        for _ in range(60):
            if s.ok():
                break
            time.sleep(1)
        else:
            p.kill()
            raise RuntimeError("Jupyter 没起来，见 data/practice/jupyter-local.log")
        return {"port": port, "token": token, "info": {"pid": p.pid}}

    def install(self, course: dict, say) -> None:
        src = course_src(course)
        if src and not (self.work / course["id"]).exists():
            (self.work / course["id"]).symlink_to(src)
        pkgs = pip_pkgs(course, skip_torch=True)
        if pkgs:
            say(f"安装课程依赖：{' '.join(pkgs)}")
            uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
            r = _run([uv, "pip", "install", "--python", self.py(), *pkgs], timeout=1800)
            if r.returncode:
                raise RuntimeError("装课程依赖失败：" + r.stderr[-400:])

    def shutdown(self, r: dict, say) -> None:
        pid = r["info"].get("pid")
        if pid:
            try:
                os.killpg(pid, 15)
            except OSError:
                pass


class Cloud:
    kind = "cloud"

    def __init__(self, runner=None):
        self.c = cfg()
        self.key = ROOT / "ssh" / "id_ed25519"
        self.runner = runner or (lambda cmd, timeout=600: _run(cmd, timeout=timeout, env=_env_noproxy()))

    # aliyun CLI
    def ali(self, *args, timeout: int = 120) -> dict:
        r = self.runner(["aliyun", "--profile", self.c["profile"], *args], timeout=timeout)
        try:
            out = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            out = {}
        if r.returncode:
            raise RuntimeError(f"aliyun {args[0]} {args[1]} 失败：" + ((r.stdout or "") + (r.stderr or ""))[-400:])
        return out

    def ssh_base(self, ip: str) -> list[str]:
        return ["ssh", "-i", str(self.key), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=20", "-o", "LogLevel=ERROR", f"root@{ip}"]

    def sh(self, cmd: str, timeout: int = 1800) -> tuple[int, str]:
        ip = state("cloud")["info"].get("ip")
        r = self.runner([*self.ssh_base(ip), cmd], timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-4000:]

    def put(self, local: Path, remote: str) -> None:
        ip = state("cloud")["info"].get("ip")
        r = self.runner(["scp", "-i", str(self.key), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                         "-o", "LogLevel=ERROR", str(local), f"root@{ip}:{remote}"], timeout=900)
        if r.returncode:
            raise RuntimeError("上传失败：" + (r.stderr or "")[-300:])

    def get(self, remote: str, local: Path) -> None:
        ip = state("cloud")["info"].get("ip")
        local.parent.mkdir(parents=True, exist_ok=True)
        r = self.runner(["scp", "-i", str(self.key), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                         "-o", "LogLevel=ERROR", f"root@{ip}:{remote}", str(local)], timeout=1800)
        if r.returncode:
            raise RuntimeError("下载失败：" + (r.stderr or "")[-300:])

    def price(self) -> tuple[str, float]:
        best = None
        for z in self.c["zones"]:
            h = self.ali("ecs", "DescribeSpotPriceHistory", "--RegionId", self.c["region"], "--ZoneId", z, "--NetworkType", "vpc",
                         "--InstanceType", self.c["instance_type"], "--OSType", "linux")
            ps = h.get("SpotPrices", {}).get("SpotPriceType", [])
            if ps:
                p = float(ps[-1]["SpotPrice"])
                if best is None or p < best[1]:
                    best = (z, p)
        if not best:
            raise RuntimeError("查不到抢占式价格（这个可用区没有库存？）")
        return best

    def network(self, zone: str, say) -> dict:
        """VPC 用账号里已有的；practice 专用的交换机 / 安全组 / 密钥对没有就建（都不收费）。"""
        R = self.c["region"]
        vpcs = self.ali("vpc", "DescribeVpcs", "--RegionId", R).get("Vpcs", {}).get("Vpc", [])
        if not vpcs:
            raise RuntimeError(f"{R} 没有 VPC，请先在控制台建一个")
        vpc = vpcs[0]["VpcId"]
        vsw = [x for x in self.ali("vpc", "DescribeVSwitches", "--RegionId", R, "--VpcId", vpc, "--ZoneId", zone, "--PageSize", "50")
               .get("VSwitches", {}).get("VSwitch", [])]
        if vsw:
            vsw_id = vsw[0]["VSwitchId"]
        else:
            say(f"在 {zone} 建交换机（免费）")
            vsw_id = self.ali("vpc", "CreateVSwitch", "--RegionId", R, "--VpcId", vpc, "--ZoneId", zone,
                              "--CidrBlock", self.c["vsw_cidr"], "--VSwitchName", "ss-practice")["VSwitchId"]
            time.sleep(5)
        sgs = [x for x in self.ali("ecs", "DescribeSecurityGroups", "--RegionId", R, "--VpcId", vpc, "--SecurityGroupName", "ss-practice-sg")
               .get("SecurityGroups", {}).get("SecurityGroup", [])]
        if sgs:
            sg = sgs[0]["SecurityGroupId"]
        else:
            say("建安全组：只开 SSH 22 端口（免费）")
            sg = self.ali("ecs", "CreateSecurityGroup", "--RegionId", R, "--VpcId", vpc, "--SecurityGroupName", "ss-practice-sg",
                          "--Description", "self_startup practice: ssh only")["SecurityGroupId"]
            self.ali("ecs", "AuthorizeSecurityGroup", "--RegionId", R, "--SecurityGroupId", sg, "--IpProtocol", "tcp",
                     "--PortRange", "22/22", "--SourceCidrIp", "0.0.0.0/0", "--Description", "ssh key-only")
        if not self.key.exists():
            self.key.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "ss-practice", "-f", str(self.key)], capture_output=True, check=True)
        kps = self.ali("ecs", "DescribeKeyPairs", "--RegionId", R, "--KeyPairName", "ss-practice").get("KeyPairs", {}).get("KeyPair", [])
        if not kps:
            say("导入 SSH 公钥（免费）")
            self.ali("ecs", "ImportKeyPair", "--RegionId", R, "--KeyPairName", "ss-practice",
                     "--PublicKeyBody", (self.key.with_suffix(".pub")).read_text().strip())
        return {"vsw": vsw_id, "sg": sg}

    def image(self) -> str:
        ims = self.ali("ecs", "DescribeImages", "--RegionId", self.c["region"], "--ImageOwnerAlias", "system", "--OSType", "linux",
                       "--InstanceType", self.c["instance_type"], "--PageSize", "100").get("Images", {}).get("Image", [])
        ok = sorted([x["ImageId"] for x in ims if x["ImageId"].startswith(self.c["image_like"])], reverse=True)
        if not ok:
            raise RuntimeError("找不到预装 GPU 驱动的 Ubuntu 镜像")
        return ok[0]

    def boot(self, say) -> dict:
        r0 = state("cloud")
        zone, price = r0["info"].get("zone"), r0.get("price")
        if not zone:
            zone, price = self.price()
        net = self.network(zone, say)
        hours = max(1.0, self.c["cap_yuan"] / (price + self.c["disk_yuan_h"]))
        release = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:00Z")
        say(f"开机：{self.c['instance_type']}（A10 24GB）抢占式 · {zone} · 约 {price} 元/小时 · 最晚 {hours:.1f} 小时后自动释放")
        _check_cancel("cloud")
        res = self.ali("ecs", "RunInstances", "--RegionId", self.c["region"], "--ZoneId", zone, "--InstanceType", self.c["instance_type"],
                       "--ImageId", self.image(), "--SecurityGroupId", net["sg"], "--VSwitchId", net["vsw"], "--KeyPairName", "ss-practice",
                       "--InstanceChargeType", "PostPaid", "--SpotStrategy", "SpotAsPriceGo", "--InternetChargeType", "PayByTraffic",
                       "--InternetMaxBandwidthOut", "100", "--SystemDisk.Category", "cloud_essd", "--SystemDisk.Size", "100",
                       "--InstanceName", "ss-practice", "--AutoReleaseTime", release, "--Tag.1.Key", "ss-practice", "--Tag.1.Value", "1",
                       "--Amount", "1", "--ClientToken", r0["info"].get("client_token") or secrets.token_hex(16), timeout=180)
        iid = res["InstanceIdSets"]["InstanceIdSet"][0]
        _set("cloud", info={**state("cloud")["info"], "instance": iid, "zone": zone})
        ip = ""
        for _ in range(60):
            ins = self.ali("ecs", "DescribeInstances", "--RegionId", self.c["region"], "--InstanceIds", json.dumps([iid])) \
                .get("Instances", {}).get("Instance", [])
            if ins and ins[0]["Status"] == "Running":
                ip = (ins[0].get("PublicIpAddress", {}).get("IpAddress") or [""])[0]
                if ip:
                    break
            time.sleep(5)
            _check_cancel("cloud")
        if not ip:
            raise RuntimeError("实例没有进入运行状态")
        _set("cloud", info={**state("cloud")["info"], "ip": ip})
        say(f"已开机 {ip}，等 SSH 就绪")
        for _ in range(40):
            if self.runner([*self.ssh_base(ip), "true"], timeout=20).returncode == 0:
                break
            time.sleep(5)
        else:
            raise RuntimeError("SSH 连不上")
        _check_cancel("cloud")
        say("安装 Python 环境、PyTorch、Jupyter（阿里云镜像源，约 3–5 分钟）")
        self.put(ASSETS / "cloud_setup.sh", "/root/cloud_setup.sh")
        token = secrets.token_hex(16)
        code, out = self.sh(f"SS_TOKEN={token} bash /root/cloud_setup.sh", timeout=1800)
        for line in out.splitlines()[-6:]:
            say("  " + line)
        if code:
            raise RuntimeError("云端环境安装失败（见日志）")
        port = _free_port()
        tun = subprocess.Popen([*self.ssh_base(ip)[:-1], "-N", "-L", f"{port}:127.0.0.1:8888",
                                "-R", f"18780:127.0.0.1:{gateway_port()}", "-o", "ExitOnForwardFailure=yes", f"root@{ip}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=_env_noproxy())
        s = K.Server(f"http://127.0.0.1:{port}", token)
        for _ in range(30):
            if s.ok():
                break
            time.sleep(1)
        else:
            tun.kill()
            raise RuntimeError("隧道或 Jupyter 不通")
        return {"port": port, "token": token, "info": {**state("cloud")["info"], "tunnel": tun.pid}}

    def install(self, course: dict, say) -> None:
        say(f"上传课程「{course['title']}」代码")
        self.put(bundle(course), f"/root/bundle-{course['id']}.tar.gz")
        pkgs = " ".join(shlex.quote(p) for p in pip_pkgs(course))
        code, out = self.sh(f"cd /root/work && tar xzf /root/bundle-{course['id']}.tar.gz && "
                            + (f"/root/venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ {pkgs}" if pkgs else "true"),
                            timeout=1800)
        if code:
            raise RuntimeError("装课程依赖失败：" + out[-400:])

    def shutdown(self, r: dict, say) -> None:
        info = r["info"]
        try:
            if info.get("ip") and info.get("tunnel"):
                self.pull_weights(info, say)
        except Exception as e:  # noqa: BLE001
            say("拉回权重失败（照常释放实例）：" + str(e)[:300])
        finally:
            if info.get("tunnel"):
                try:
                    os.killpg(info["tunnel"], 15)
                except OSError:
                    pass
            if info.get("instance"):
                self.release(info["instance"], say)

    def pull_weights(self, info: dict, say) -> None:
        for c in [x.split("@")[0] for x in info.get("courses", [])]:
            code, out = self.sh(f"cd /root/work/{shlex.quote(c)} && find out -name '*.pth' -newer /root/bundle-{shlex.quote(c)}.tar.gz 2>/dev/null | head -20", timeout=60)
            files = [x for x in out.split() if x.endswith(".pth")]
            if files:
                say(f"拉回 {c} 在云上训出的权重 {len(files)} 个（存为 out/cloud_*.pth，不覆盖本机的）")
                for f in files:
                    self.get(f"/root/work/{c}/{f}", Local().work / c / "out" / ("cloud_" + Path(f).name))

    def release(self, iid: str, say, tries: int = 12) -> None:
        """DeleteInstance --Force；实例还在 Pending / Starting 时会报错，隔 10 秒重试，最多约 2 分钟。"""
        say(f"释放实例 {iid}")
        for i in range(tries):
            try:
                self.ali("ecs", "DeleteInstance", "--InstanceId", iid, "--Force", "true")
                return
            except RuntimeError as e:
                if "NotFound" in str(e):
                    return
                if i == tries - 1:
                    raise
                time.sleep(10)

    def orphans(self, keep: str = "") -> list[str]:
        ins = self.ali("ecs", "DescribeInstances", "--RegionId", self.c["region"], "--Tag.1.Key", "ss-practice", "--Tag.1.Value", "1",
                       "--PageSize", "50").get("Instances", {}).get("Instance", [])
        return [x["InstanceId"] for x in ins if x["InstanceId"] != keep]


RUNNERS = {"local": Local, "cloud": Cloud}
_locks = {k: threading.Lock() for k in RUNNERS}
_state_lock = threading.Lock()


class Cancelled(RuntimeError):
    pass


def _check_cancel(kind: str) -> None:
    if state(kind)["status"] != "starting":
        raise Cancelled("开机中被停止")


# ---------- 云端只能经反向隧道调平台的这两个接口（云上跑的是第三方代码，不能碰平台其余 API） ----------

GATEWAY_PATHS = ("/api/practice/llm", "/api/practice/pull")
_gateway: list[int] = []


class _Gateway(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path not in GATEWAY_PATHS:
            self.send_error(403)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            r = httpx.post(f"http://127.0.0.1:{platform_port()}{self.path}", content=body,
                           headers={"Content-Type": "application/json"}, timeout=1800, trust_env=False)
            code, data = r.status_code, r.content
        except httpx.HTTPError as e:
            code, data = 502, json.dumps({"detail": str(e)}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def gateway_port() -> int:
    with _state_lock:
        if not _gateway:
            srv = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
            threading.Thread(target=srv.serve_forever, daemon=True, name="practice-gateway").start()
            _gateway.append(srv.server_address[1])
        return _gateway[0]


def runner(kind: str):
    return RUNNERS[kind]()


def start(kind: str, quote: bool = False) -> dict:
    """开运行环境（后台线程）。云端先查价格返回给前端确认，quote=True 只报价不开机。"""
    if kind == "cloud":
        c = Cloud()
        zone, price = c.price()
        price = round(price + c.c["disk_yuan_h"], 3)
        q = {"zone": zone, "price": price, "cap": c.c["cap_yuan"], "idle_min": c.c["idle_min"],
             "hours": round(c.c["cap_yuan"] / price, 1), "instance_type": c.c["instance_type"]}
        if quote:
            return q
    with _state_lock:
        r = state(kind)
        if r["status"] in ("starting", "ready", "stopping"):
            return view(kind)
        _set(kind, status="starting", error="", log="", started_at=time.time() if kind == "cloud" else None, stopped_at=None,
             ready_at=None, last_active=time.time(),
             **({"price": price, "cap": c.c["cap_yuan"], "info": {"zone": zone, "client_token": secrets.token_hex(16)}}
                if kind == "cloud" else {"info": {}}))

    def go():
        with _locks[kind]:
            say = lambda s: _log(kind, s)  # noqa: E731
            try:
                got = runner(kind).boot(say)
                with _state_lock:
                    cancelled = state(kind)["status"] != "starting"
                    info = {**state(kind)["info"], **got["info"], "courses": []}
                    if cancelled:
                        _set(kind, info=info)
                    else:
                        _set(kind, status="ready", port=got["port"], token=got["token"], info=info, ready_at=time.time(), last_active=time.time())
                if cancelled:
                    raise Cancelled("开机中被停止")
                say("就绪")
            except Exception as e:  # noqa: BLE001
                cancelled = isinstance(e, Cancelled)
                if not cancelled:
                    log.exception("practice runtime %s boot failed", kind)
                say(("已取消开机" if cancelled else "失败：" + str(e)) + "，清理中")
                try:
                    runner(kind).shutdown(state(kind), say)
                    if kind == "cloud":
                        _sweep(say)
                    _set(kind, status="stopped" if cancelled else "failed", error="" if cancelled else str(e)[:500],
                         stopped_at=time.time(), port=None, token=None)
                except Exception as e2:  # noqa: BLE001
                    say("清理失败：" + str(e2) + "（实例仍会在自动释放时间到点释放，可再点停止重试）")
                    _set(kind, status="failed", error=("清理失败：" + str(e2))[:500], stopped_at=time.time())
    threading.Thread(target=go, daemon=True, name=f"practice-boot-{kind}").start()
    return view(kind)


def stop(kind: str, reason: str = "手动停止") -> dict:
    with _state_lock:
        r = state(kind)
        if r["status"] in ("stopped", "stopping"):
            return view(kind)
        _set(kind, status="stopping")
    if r["status"] == "starting":
        _log(kind, f"停止：{reason}（等开机线程收尾后释放）")
        return view(kind)

    def go():
        say = lambda s: _log(kind, s)  # noqa: E731
        say(f"停止：{reason}")
        try:
            runner(kind).shutdown(state(kind), say)
            if kind == "cloud":
                _sweep(say)
            _set(kind, status="stopped", stopped_at=time.time(), port=None, token=None)
            say(f"已停止 · 本次约 {cost(state(kind))} 元" if kind == "cloud" else "已停止")
        except Exception as e:  # noqa: BLE001
            say("停止失败：" + str(e))
            _set(kind, status="failed", error=str(e)[:500], stopped_at=time.time())
    threading.Thread(target=go, daemon=True, name=f"practice-stop-{kind}").start()
    return view(kind)


def ensure_course(kind: str, course: dict) -> None:
    """课程装过、且依赖没变就跳过；course.json 的 pip 改了会重装。"""
    import hashlib
    key = course["id"] + "@" + hashlib.md5(json.dumps(course.get("pip", [])).encode()).hexdigest()[:8]
    if key in state(kind)["info"].get("courses", []):
        return
    with _locks[kind]:
        r = state(kind)
        if key in r["info"].get("courses", []):
            return
        runner(kind).install(course, lambda s: _log(kind, s))
        keep = [x for x in r["info"].get("courses", []) if x.split("@")[0] != course["id"]]
        _set(kind, info={**r["info"], "courses": [*keep, key]})


def _sweep(say) -> None:
    """按标签找 ss-practice 的实例，除了当前在用的都释放（RunInstances 超时、平台重启丢了实例 id 时兜底）。"""
    r = state("cloud")
    keep = r["info"].get("instance", "") if r["status"] in ("starting", "ready") else ""
    c = Cloud()
    for iid in c.orphans(keep):
        say(f"发现遗留实例 {iid}，释放")
        c.release(iid, say)


def _kernel_busy(kind: str) -> bool:
    """运行环境里还有内核在跑（平台重启后执行线程没了，但云上训练可能还在继续）。"""
    s = server(kind)
    if not s:
        return False
    try:
        ks = httpx.get(s.base + "/api/kernels", headers=s._h(), timeout=10, trust_env=False).json()
    except (httpx.HTTPError, ValueError):
        return False
    return any(k.get("execution_state") == "busy" for k in ks)


def guard() -> str:
    """看门狗：云端空闲超时或花费到上限就停。返回停止原因（测试用）。"""
    r = state("cloud")
    if r["status"] != "ready":
        return ""
    c = cfg()
    if cost(r) >= (r.get("cap") or c["cap_yuan"]):
        stop("cloud", f"到花费上限 {r.get('cap') or c['cap_yuan']} 元")
        return "cap"
    if not K.running() and time.time() - (r.get("last_active") or 0) > c["idle_min"] * 60:
        if _kernel_busy("cloud"):
            touch("cloud")
            return ""
        stop("cloud", f"空闲超过 {c['idle_min']} 分钟")
        return "idle"
    return ""


def _guard_loop():
    while True:
        time.sleep(60)
        try:
            guard()
        except Exception:  # noqa: BLE001
            log.exception("practice guard")


def on_startup():
    for kind in RUNNERS:
        r = state(kind)
        lost = r["status"] in ("starting", "stopping") or (r["status"] == "ready" and not (server(kind) and server(kind).ok()))
        if lost and kind == "local":
            _set(kind, status="stopped", error="")
        elif lost:
            _set(kind, status="ready")
            stop(kind, "平台重启后连不上云端运行环境，释放实例")
        elif kind == "cloud" and r["status"] == "failed" and r["info"].get("instance"):
            stop(kind, "上次释放失败，重试")
    threading.Thread(target=_guard_loop, daemon=True, name="practice-guard").start()
