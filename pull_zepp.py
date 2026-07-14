"""Pull VexCom zepp source from Barrow."""
import urllib.request, json, os

with open("vex_peers.json") as f:
    barrow = json.loads(f.read())["peers"]["bluce"]
h = {"Content-Type": "application/json", "Authorization": f"Bearer {barrow['token']}"}

def read(path):
    body = json.dumps({"tool": "read_file", "args": {"path": path}})
    req = urllib.request.Request(f"{barrow['url']}/tools", data=body.encode(), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r = json.loads(r.read().decode())
        return r.get("content", "") if r.get("ok") else None

base_src = "/home/aldous/Desktop/vex/vex_voice/zepp"
base_dst = "/home/aldous/vex/vex_voice/zepp"
files = ["app.json", "app.js", "package.json", "README.md",
         "pages/index.js", "app-side/index.js", "setting/index.js"]

for f in files:
    content = read(f"{base_src}/{f}")
    if content:
        dst = os.path.join(base_dst, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as fh:
            fh.write(content)
        print(f"  {f} ({len(content):,}b)")

print(f"\nDone — {len(files)} files at {base_dst}/")
