import json, time
from pathlib import Path
from rlmath.core import leancode
from rlmath.families import case_tree as ct
from rlmath.lean.repl_pool import ReplPool
OUT = Path("/Users/tom/code/playground/rlmath/data/families/ct_battery")
t0=time.time()
pool = ReplPool(n_workers=4); pool.warm()
rows=[]
try:
    for name,k,hb in [("r1_recip",64,400000),("r3_floor",64,400000),
                      ("v2",128,1600000),("r1_recip",128,400000)]:
        p = ct.build(k, 5150, 0, preset=name)
        art = leancode.compose(p.goal, p.oracle_plan, p.witness_proofs())
        code = art if hb==400000 else f"set_option maxHeartbeats {hb} in\n{art}"
        t=time.time(); r = pool.check(code, timeout_s=900.0)
        row={"rung":name,"k":k,"maxHeartbeats":hb,"ok":bool(r.ok and r.sorries==0),
             "seconds":round(time.time()-t,1),"artifact_chars":len(art),
             "err":[m.text[:70] for m in r.errors][:1]}
        rows.append(row); print(row, flush=True)
finally:
    pool.close()
prev=json.load(open(OUT/"gate_heartbeat.json"))
prev["rows"] += rows
prev["seconds"] = round(prev["seconds"]+time.time()-t0,1)
(OUT/"gate_heartbeat.json").write_text(json.dumps(prev,ensure_ascii=False,indent=2))
print("appended")
