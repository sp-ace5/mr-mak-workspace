extends SceneTree
# Usage: godot --headless --path playground --script res://tools/sync_packs.gd -- <abs addon dir>...
# Copies each given addon folder (factory/dist/<pack>/addons/<pack>) to res://addons/<pack>, replacing it,
# and removes addons an earlier sync added that are no longer given. Addons installed by hand are left alone:
# only names in res://addons/.factory_synced.json are ever removed. Prints "err=0" last on success.

const ADDONS := "res://addons"
const LEDGER := "res://addons/.factory_synced.json"


func _init() -> void:
	var err := _sync(OS.get_cmdline_user_args())
	print("err=%d" % err)
	quit(0 if err == OK else 1)


func _sync(sources: PackedStringArray) -> int:
	var root := ProjectSettings.globalize_path(ADDONS)
	DirAccess.make_dir_recursive_absolute(root)
	# Only real pack ids ever become paths: an empty, "." or ".." entry would reach outside one addon folder.
	var pack_id := RegEx.create_from_string("^[a-z][a-z0-9_]*$")
	var before: Array = []
	if FileAccess.file_exists(LEDGER):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(LEDGER))
		if parsed is Array:
			before = parsed.filter(func(id): return id is String and pack_id.search(id) != null)
	var now: Array = []
	var err := OK
	for source in sources:
		var src := source.replace("\\", "/").trim_suffix("/")
		var id := src.get_file()
		if pack_id.search(id) == null or not DirAccess.dir_exists_absolute(src):
			printerr("not a pack addon folder: ", source)
			err = ERR_INVALID_PARAMETER
			break
		if DirAccess.dir_exists_absolute(root.path_join(id)) and not before.has(id):
			printerr("addons/", id, " was installed by hand; not replacing it")
			err = ERR_ALREADY_EXISTS
			break
		now.append(id)   # recorded before copying, so a half-copied folder is still ours to remove later
		_remove(root.path_join(id))
		err = _copy(src, root.path_join(id))
		if err != OK:
			printerr("copy failed for ", id, ": ", error_string(err))
			break
		print("synced ", id)
	var owned := now.duplicate()
	for id in before:
		if owned.has(id):
			continue
		if err == OK:
			_remove(root.path_join(id))
			print("removed ", id)
		else:
			owned.append(id)   # a failed run removes nothing, but keeps track of everything it may own
	var ledger := FileAccess.open(LEDGER, FileAccess.WRITE)
	if ledger == null:
		return FileAccess.get_open_error()
	ledger.store_string(JSON.stringify(owned))
	return err


func _copy(src: String, dst: String) -> int:
	var err := DirAccess.make_dir_recursive_absolute(dst)
	if err != OK:
		return err
	for name in DirAccess.get_files_at(src):
		err = DirAccess.copy_absolute(src.path_join(name), dst.path_join(name))
		if err != OK:
			return err
	for name in DirAccess.get_directories_at(src):
		err = _copy(src.path_join(name), dst.path_join(name))
		if err != OK:
			return err
	return OK


func _remove(path: String) -> void:
	if not DirAccess.dir_exists_absolute(path):
		return
	for name in DirAccess.get_files_at(path):
		DirAccess.remove_absolute(path.path_join(name))
	for name in DirAccess.get_directories_at(path):
		_remove(path.path_join(name))
	DirAccess.remove_absolute(path)
