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
	var before: Array = []
	if FileAccess.file_exists(LEDGER):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(LEDGER))
		if parsed is Array:
			before = parsed
	var now: Array = []
	for source in sources:
		var src := source.replace("\\", "/").trim_suffix("/")
		var id := src.get_file()
		if id.is_empty() or not DirAccess.dir_exists_absolute(src):
			printerr("not an addon folder: ", source)
			return ERR_FILE_NOT_FOUND
		_remove(root.path_join(id))
		var err := _copy(src, root.path_join(id))
		if err != OK:
			printerr("copy failed for ", id, ": ", error_string(err))
			return err
		now.append(id)
		print("synced ", id)
	for id in before:
		if not now.has(id):
			_remove(root.path_join(str(id)))
			print("removed ", id)
	var ledger := FileAccess.open(LEDGER, FileAccess.WRITE)
	if ledger == null:
		return FileAccess.get_open_error()
	ledger.store_string(JSON.stringify(now))
	return OK


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
