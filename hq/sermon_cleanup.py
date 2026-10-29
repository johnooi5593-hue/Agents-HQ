"""Receipt-bound cleanup of HQ delivery copies, never source artwork or approved work."""
import argparse
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(root, file):
    root, file = Path(root).absolute(), Path(file).absolute()
    file.relative_to(root)
    cursor = file
    while True:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("Cleanup refuses links and junctions")
        if cursor == root:
            break
        if cursor == cursor.parent:
            raise ValueError("Cleanup path escapes its owned area")
        cursor = cursor.parent
    return file


def file_record(root, file):
    file = checked(root, file)
    stat = file.stat()
    if not file.is_file() or stat.st_nlink != 1:
        raise ValueError("Cleanup requires an exclusive regular file")
    return {"path": str(file), "size": stat.st_size, "sha256": digest(file.read_bytes())}


def atomic_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, file)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def index_lock(hq_root):
    hq = Path(hq_root).resolve()
    lock = checked(hq, hq / "hq/sermon-project-links.cleanup.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    checked(hq, lock)
    deadline = time.monotonic() + 10
    while True:
        try:
            stream = lock.open("x", encoding="utf-8")
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError("Another delivery update is in progress; retry without deleting anything")
            time.sleep(.05)
    try:
        with stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def board_lock(hq_root):
    """Use the exact cross-process task lock used by server.py and tasks.js."""
    hq = Path(hq_root).resolve()
    lock = checked(hq, hq / "hq/tasks.lock")
    deadline = time.monotonic() + 5
    fd = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError("HQ task board is busy. No offline cleanup was started")
            time.sleep(.02)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def plan_cleanup(hq_root, runtime_root, project_ids=None):
    hq, runtime = Path(hq_root).resolve(), Path(runtime_root).resolve()
    index_file = checked(hq, hq / "hq/sermon-project-links.json")
    index_bytes = index_file.read_bytes() if index_file.exists() else b'{"version":1,"deliveries":{}}'
    index = json.loads(index_bytes)
    if index.get("version") != 1 or not isinstance(index.get("deliveries"), dict):
        raise ValueError("Invalid delivery index; nothing was deleted")
    task_file = checked(hq, hq / "hq/tasks.json")
    task_bytes = task_file.read_bytes() if task_file.exists() else b'{"tasks":[],"deleted":[]}'
    tasks = json.loads(task_bytes)
    selected = set(project_ids) if project_ids is not None else None
    if selected is not None and (not selected or any(not re.fullmatch(ID, str(pid)) for pid in selected)):
        raise ValueError("Choose exact project IDs")
    plan = {"version": 1, "folders": [], "kept": [], "fileCount": 0, "bytes": 0, "indexSha256": digest(index_bytes), "tasksSha256": digest(task_bytes), "selectedProjectIds": sorted(selected) if selected is not None else []}
    for key, delivery in index["deliveries"].items():
        pid, folder = delivery.get("projectId"), delivery.get("folder", "")
        if selected is not None and pid not in selected:
            continue
        if delivery.get("cleanup", {}).get("status") == "purged" and not delivery.get("cleanup", {}).get("taskRemovalPending"):
            continue
        if not re.fullmatch(ID, str(pid)) or not re.fullmatch(r"sermon-studio-" + re.escape(pid) + r"-r\d+-a\d+", folder):
            raise ValueError("Delivery identity is invalid")
        marker = checked(runtime, runtime / ".studio/sermon-design/purged" / (pid + ".json"))
        if not marker.exists():
            plan["kept"].append({"folder": folder, "reason": "project-not-permanently-purged"}); continue
        raw = marker.read_bytes(); receipt = json.loads(raw)
        current = checked(runtime, runtime / ".studio/sermon-design/projects" / pid / "project.json")
        if receipt.get("projectId") != pid or receipt.get("version") != 1 or receipt.get("status") != "purged" or current.exists():
            plan["kept"].append({"folder": folder, "reason": "project-purge-incomplete"}); continue
        if (hq / "approved" / folder).exists():
            plan["kept"].append({"folder": folder, "reason": "approved-copy-protected"}); continue
        directory = checked(hq / "out", hq / "out" / folder)
        if not directory.exists():
            plan["folders"].append({"key": key, "projectId": pid, "taskId": delivery.get("taskId"), "folder": folder, "files": [], "missing": True, "receiptPath": str(marker), "receiptSha256": digest(raw)}); continue
        peers = [record for other_key, record in index["deliveries"].items() if other_key != key and record.get("folder", "").casefold() == folder.casefold()]
        foreign_tasks = [t for t in tasks.get("tasks", []) if t.get("id") != delivery.get("taskId") and ("out:" + folder) in str(t.get("note", "")).split()]
        if peers or foreign_tasks:
            plan["kept"].append({"folder": folder, "reason": "shared-delivery-reference"}); continue
        expected, files = {}, []
        for item in delivery.get("files", []):
            name = item.get("name", "").replace("\\", "/")
            if not name or name.startswith("/") or ":" in name or any(p in ("", ".", "..") for p in name.split("/")) or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))):
                raise ValueError("Unsafe delivery file identity")
            if name.casefold() in expected:
                raise ValueError("Duplicate delivery file identity")
            expected[name.casefold()] = item
        try:
            for entry in directory.rglob("*"):
                checked(directory, entry)
                if entry.is_dir():
                    continue
                record = file_record(directory, entry)
                relative = entry.relative_to(directory).as_posix()
                item = expected.get(relative.casefold())
                if item:
                    if record["size"] != item.get("size") or record["sha256"] != item["sha256"]:
                        raise ValueError("Delivery copy changed")
                elif relative == "README.md":
                    text = entry.read_text(encoding="utf-8")
                    if not text.startswith("# Sermon Design Studio delivery\n\nNative Resvg/Sharp renderer;") or "\n\nProject: " + pid + "\nRevision: " + str(delivery.get("revision")) + "\n" not in text:
                        raise ValueError("Unrecognized README file")
                else:
                    raise ValueError("Unowned file in delivery folder: " + relative)
                files.append(record)
            if not expected:
                raise ValueError("No verified delivery files")
        except (OSError, ValueError) as error:
            plan["kept"].append({"folder": folder, "reason": str(error)}); continue
        plan["folders"].append({"key": key, "projectId": pid, "taskId": delivery.get("taskId"), "folder": folder, "files": sorted(files, key=lambda row: row["path"]), "missing": False, "receiptPath": str(marker), "receiptSha256": digest(raw)})
        plan["fileCount"] += len(files); plan["bytes"] += sum(row["size"] for row in files)
    plan["signature"] = digest(json.dumps(plan, sort_keys=True).encode())
    return plan


def execute_cleanup(hq_root, runtime_root, expected, task_action=None):
    with index_lock(hq_root):
        return _execute_cleanup(hq_root, runtime_root, expected, task_action)


def _execute_cleanup(hq_root, runtime_root, expected, task_action=None):
    hq = Path(hq_root).resolve()
    ids = sorted({item["projectId"] for item in expected.get("folders", [])} | set(expected.get("selectedProjectIds", [])))
    blockers = [row for row in expected.get("kept", []) if row.get("reason") != "project-not-permanently-purged"]
    if not ids:
        return {"status": "partial" if blockers else "no-change", "deletedFiles": 0, "deletedBytes": 0, "cleanedFolders": [], "errors": blockers}
    actual = plan_cleanup(hq_root, runtime_root, ids)
    # A preview made without a selection has the same scoped content but retained outsiders differ.
    compare = lambda p: {k: p[k] for k in ("folders", "indexSha256", "tasksSha256")}
    if compare(actual) != compare(expected):
        raise ValueError("Delivery copies changed since the preview. Preview again; no files were deleted")
    audit_path = checked(hq, hq / "hq/sermon-cleanup-receipts" / (str(int(time.time() * 1000)) + "-" + uuid.uuid4().hex + ".json"))
    result = {"version": 1, "status": "partial", "deletedFiles": 0, "deletedBytes": 0, "cleanedFolders": [], "errors": blockers, "plan": actual, "receiptPath": str(audit_path)}
    atomic_json(audit_path, result)
    for item in actual["folders"]:
        directory = checked(hq / "out", hq / "out" / item["folder"])
        try:
            # Fresh checks occur immediately before each precise unlink; never recursive-delete.
            for record in item["files"]:
                check = file_record(directory, record["path"])
                if check != record:
                    raise ValueError("A copied file changed before removal")
                Path(record["path"]).unlink(); result["deletedFiles"] += 1; result["deletedBytes"] += record["size"]
            if directory.exists():
                for child in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    checked(directory, child)
                    if child.is_dir():
                        child.rmdir()
                directory.rmdir()
            result["cleanedFolders"].append(item["folder"])
        except (OSError, ValueError) as error:
            result["errors"].append({"folder": item["folder"], "error": str(error)}); continue
    index_file = hq / "hq/sermon-project-links.json"
    index = json.loads(index_file.read_text(encoding="utf-8"))
    for item in actual["folders"]:
        if item["folder"] not in result["cleanedFolders"]:
            continue
        delivery = index["deliveries"][item["key"]]
        delivery["cleanup"] = {"status": "purged", "at": time.time(), "receiptPath": str(audit_path), "taskRemovalPending": True}
        if task_action:
            try:
                code, payload = task_action({"action": "remove", "id": item["taskId"]})
                if code not in (200, 404):
                    raise ValueError("Linked HQ task could not be removed")
                delivery["cleanup"]["taskRemovalPending"] = False
            except Exception as error:
                result["errors"].append({"folder": item["folder"], "error": str(error)})
    if not task_action:
        # Offline repair only: require the exact task ledger from the preview.
        # A live bridge supplies task_action, which uses the app's task lock.
        try:
            with board_lock(hq):
                task_file = hq / "hq/tasks.json"
                task_bytes = task_file.read_bytes() if task_file.exists() else b'{"tasks":[],"deleted":[]}'
                if digest(task_bytes) != actual["tasksSha256"]:
                    result["errors"].append({"error": "HQ tasks changed; linked cards were not modified. Reconcile again."})
                else:
                    db = json.loads(task_bytes)
                    removed = {item["taskId"]: item["folder"] for item in actual["folders"] if item["folder"] in result["cleanedFolders"]}
                    keep = []
                    for task in db.get("tasks", []):
                        folder = removed.get(task.get("id"))
                        if folder and ("out:" + folder) in str(task.get("note", "")).split():
                            db.setdefault("deleted", []).append({**task, "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "studioPermanentlyDeleted": True})
                        else:
                            keep.append(task)
                    db["tasks"] = keep
                    atomic_json(task_file, db)
                    for item in actual["folders"]:
                        if item["folder"] in result["cleanedFolders"]:
                            index["deliveries"][item["key"]]["cleanup"]["taskRemovalPending"] = False
        except (OSError, ValueError) as error:
            result["errors"].append({"error": "HQ task synchronization remains pending: " + str(error)})
    if digest(index_file.read_bytes()) != actual["indexSha256"]:
        result["errors"].append({"error": "Delivery index changed while cleaning; current index preserved. Reconcile again."})
        result["status"] = "partial"
        atomic_json(audit_path, result)
        return result
    atomic_json(index_file, index)
    result["status"] = "partial" if result["errors"] else "purged"
    atomic_json(audit_path, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hq-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--runtime-root", default=r"D:\AI OFFICE\.studio\sermon-design-runtime")
    parser.add_argument("--preview", required=True, help="Save read-only preview JSON")
    parser.add_argument("--confirm-preview", help="Execute exact saved preview after owner authorization")
    args = parser.parse_args()
    if args.confirm_preview:
        result = execute_cleanup(args.hq_root, args.runtime_root, json.loads(Path(args.confirm_preview).read_text(encoding="utf-8")))
    else:
        result = plan_cleanup(args.hq_root, args.runtime_root)
    Path(args.preview).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "deletedFiles", "deletedBytes", "cleanedFolders", "errors") if k in result} or {"folders": len(result["folders"]), "files": result["fileCount"], "bytes": result["bytes"], "kept": len(result["kept"])}))
