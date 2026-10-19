// Dark Water: layered vertex waves with a fresnel rim, for murky moats and cave pools.
shader_type spatial;
render_mode specular_schlick_ggx;

uniform vec4 deep_color : source_color = vec4(0.02, 0.04, 0.06, 1.0);
uniform vec4 shallow_color : source_color = vec4(0.1, 0.25, 0.3, 1.0);
uniform float wave_height : hint_range(0.0, 0.2) = 0.03;
uniform float wave_scale : hint_range(0.5, 20.0) = 6.0;
uniform float wave_speed : hint_range(0.0, 4.0) = 1.0;
uniform float fresnel_power : hint_range(0.5, 8.0) = 3.0;
uniform float roughness_value : hint_range(0.0, 1.0) = 0.08;

varying float wave;

float waves(vec3 p, float t) {
	return sin(p.x * wave_scale + t) * 0.5
		+ sin((p.z * 0.8 + p.x * 0.6) * wave_scale * 1.3 - t * 1.2) * 0.35
		+ sin(p.y * wave_scale * 0.7 + t * 0.7) * 0.15;
}

void vertex() {
	wave = waves(VERTEX, TIME * wave_speed);
	VERTEX += NORMAL * wave * wave_height;
}

void fragment() {
	float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), fresnel_power);
	ALBEDO = mix(deep_color.rgb, shallow_color.rgb, clamp(wave * 0.5 + 0.5, 0.0, 1.0) * 0.5 + fres * 0.5);
	ROUGHNESS = roughness_value;
	METALLIC = 0.0;
	SPECULAR = 0.6;
}
