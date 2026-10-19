extends SceneTree
# Groups imported WAVs by name minus the 2-digit variation (UIClick_Hover03_... -> UIClick_Hover)
# and saves one AudioStreamRandomizer .tres per group, so buyers drop in "Hover" and get variation for free.
# Usage: godot --headless --path godot_harness --script res://make_randomizers.gd -- res://pack/audio

func _init() -> void:
	var dir: String = OS.get_cmdline_user_args()[0]
	var groups := {}
	for f in DirAccess.get_files_at(dir):
		if not f.ends_with(".wav"):
			continue
		var stem := f.get_basename()
		var parts := stem.split("_")
		# Names without "_" (not the UCS pattern) group on the stem minus its 2-digit variation.
		var key := stem.left(stem.length() - 2) if parts.size() < 2 else "%s_%s" % [parts[0], parts[1].left(parts[1].length() - 2)]
		groups.get_or_add(key, []).append(dir.path_join(f))
	for key in groups:
		var r := AudioStreamRandomizer.new()
		r.random_pitch = 1.06            # +/- ~1 semitone
		r.random_volume_offset_db = 1.5
		for p in groups[key]:
			r.add_stream(-1, load(p), 1.0)
		var out: String = dir.path_join(key + ".tres")
		var err := ResourceSaver.save(r, out)
		print("%s  streams=%d  err=%d" % [out, r.streams_count, err])
	quit()
