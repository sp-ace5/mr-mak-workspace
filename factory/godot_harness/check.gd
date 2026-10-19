extends SceneTree
# Usage: godot --headless --path godot_harness --script res://check.gd -- res://pack/a.gdshader res://pack/b.tscn
# Prints one JSON line per asset on stdout. Compile errors land on stderr between @@BEGIN/@@END markers.

func _init() -> void:
	for p in OS.get_cmdline_user_args():
		printerr("@@BEGIN ", p)
		var info := {"path": p}
		if p.ends_with(".gdshader"):
			var sh: Shader = load(p)
			var m := ShaderMaterial.new()
			m.shader = sh                      # forces a compile, even with the dummy renderer
			info["mode"] = sh.get_mode()
			info["uniforms"] = sh.get_shader_uniform_list(true)
		elif p.ends_with(".tscn"):
			var ps: PackedScene = load(p)
			var root: Node = ps.instantiate() if ps else null
			info["loaded"] = root != null
			if root:
				var amount := 0
				var emitters := 0
				for n in _walk(root):
					if n is GPUParticles3D or n is CPUParticles3D or n is GPUParticles2D or n is CPUParticles2D:
						emitters += 1
						amount += n.amount
				info["emitters"] = emitters
				info["particles_total"] = amount
				root.free()
		print(JSON.stringify(info))
		printerr("@@END ", p)
	quit()

func _walk(n: Node) -> Array:
	var out := [n]
	for c in n.get_children():
		out.append_array(_walk(c))
	return out
