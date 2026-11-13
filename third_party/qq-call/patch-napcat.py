"""仅在精确匹配的 NapCat 版本中信任本地固定散列的电话桥。"""
import hashlib
from pathlib import Path

bundle=Path('/app/napcat/napcat.mjs')
source=Path('/opt/saber/bridge/napcat-plugin')
text=bundle.read_text(encoding='utf-8')
marker='// SABER_QQ_CALL_EXACT_BRIDGE_V1'
needle='  getRejectReason(e, n) {\n    const r = this.scanSensitiveWords(n);'
hashes={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in ('index.mjs','package.json')}
replacement='  getRejectReason(e, n) {\n    // SABER_QQ_CALL_EXACT_BRIDGE_V1\n    if (e === "napcat-plugin-maibot-qq-voice-call") {\n      try {\n        if (xe.resolve(n) !== "/app/napcat/plugins/napcat-plugin-maibot-qq-voice-call") return "unexpected bridge directory";\n        const expected = __HASHES__;\n        for (const [file, digest] of Object.entries(expected)) {\n          const actual = saberBridgeCreateHash("sha256").update(fe.readFileSync(xe.join(n, file))).digest("hex");\n          if (actual !== digest) return "bridge integrity verification failed";\n        }\n        return null;\n      } catch { return "bridge integrity verification failed"; }\n    }\n    const r = this.scanSensitiveWords(n);'
import json
replacement=replacement.replace('__HASHES__',json.dumps(hashes))
if marker in text:
    if text.count(replacement)==1 and text.startswith('import { createHash as saberBridgeCreateHash }'):
        print('[qq-call] 已验证现有电话桥补丁')
        raise SystemExit(0)
    raise SystemExit('existing phone bridge patch does not match the trusted version')
if text.count(needle)!=1:
    raise SystemExit('NapCat plugin loader differs from the verified version; leaving it unchanged')
text='import { createHash as saberBridgeCreateHash } from "node:crypto";\n'+text.replace(needle,replacement,1)
tmp=bundle.with_name('.napcat.saber-call.tmp')
tmp.write_text(text,encoding='utf-8')
tmp.replace(bundle)
print('[qq-call] 仅信任已校验散列的本地电话桥')
