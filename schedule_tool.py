import argparse
import copy
import sys

from schedule_core import (load_file, save_file, desktop_data_path, clean_data,
                           DEFAULT_EVENTS, guess_resource_kind)

def main():
    p = argparse.ArgumentParser(description="????? ???????????")
    p.add_argument("--file", default=str(desktop_data_path()))
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("list")
    sub.add_parser("reset")
    rl = sub.add_parser("res-list")
    rl.add_argument("index", type=int, nargs="?")
    ra = sub.add_parser("res-add")
    ra.add_argument("index", type=int)
    ra.add_argument("target")
    ra.add_argument("--name", default=None)
    rd = sub.add_parser("res-del")
    rd.add_argument("index", type=int)
    rd.add_argument("n", type=int)

    args = p.parse_args()
    path = args.file
    try:
        data = load_file(path)
    except Exception:
        data = {}
    ev = data.setdefault("events", copy.deepcopy(DEFAULT_EVENTS))

    if args.cmd == "list" or args.cmd is None:
        for i, e in enumerate(ev, 1):
            n = len(e.get("resources", []))
            extra = f"  ({n} ????)" if n else ""
            print(f'{i:>3}  {e["day"]:<8} {e["time"]}  {e["title"]}  [{e["kind"]}]{extra}')
        return

    if args.cmd == "reset":
        data["events"] = copy.deepcopy(DEFAULT_EVENTS)
        save_file(path, data)
        print("????? ??")
        return

    if args.cmd in ("res-list", "res-add", "res-del"):
        if args.cmd == "res-list" and args.index is None:
            any_row = False
            for i, e in enumerate(ev, 1):
                for n, r in enumerate(e.get("resources", []), 1):
                    any_row = True
                    print(f'{i:>3}  {e["title"]}  #{n}  [{r["kind"]}]  {r["name"]}  ->  {r["target"]}')
            if not any_row:
                print("(??? ????? ??? ???? ???)")
            return
        if not 1 <= args.index <= len(ev):
            sys.exit(f"????? ??? ???? ??? 1 ? {len(ev)} ????.")
        e = ev[args.index - 1]
        res = e.setdefault("resources", [])
        if args.cmd == "res-add":
            target = args.target.strip()
            head = target.split("/", 1)[0]
            if "://" not in target and ("." in head or target.startswith("www.")):
                target = "https://" + target
            kind = guess_resource_kind(target)
            if any(r["target"].rstrip("/").lower() == target.rstrip("/").lower() for r in res):
                sys.exit("??? ???? ????? ????? ??? ???.")
            res.append({"name": args.name or target, "target": target, "kind": kind})
        elif args.cmd == "res-del":
            if not 1 <= args.n <= len(res):
                sys.exit(f"????? ???? ???? ??? 1 ? {len(res)} ????.")
            res.pop(args.n - 1)
        if not res:
            e.pop("resources", None)
        save_file(path, data)
        print("????? ??")
        return

if __name__ == "__main__":
    main()