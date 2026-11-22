# -*- coding: utf-8 -*-
"""derle.bat tarafindan cagrilir: senin ayarlarini (can bari bolgesi, esikler,
zamanlayicilar) paylasilacak paketin varsayilan ayari yapar. PID gibi sana ozel
seyler temizlenir."""
import json
import os
import sys

import ayar

hedef = sys.argv[1]
cfg = ayar.yukle()
cfg.get("pencere", {})["pid"] = None
cfg.get("gunluk", {})["kare_kaydet"] = False
cfg.get("ocr", {})["pid_hedefleri"] = {}      # PID'ler her bilgisayarda farkli
for a in [a for a in cfg if a.startswith("_") and a not in ("_aciklama",)]:
    cfg.pop(a, None)
with open(os.path.join(hedef, "varsayilan.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("varsayilan.json paketlendi")
