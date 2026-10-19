// Runic Glow: dark surface with procedural rune strokes that pulse with light.
shader_type spatial;

uniform vec4 base_color : source_color = vec4(0.06, 0.05, 0.07, 1.0);
uniform vec4 glow_color : source_color = vec4(0.3, 0.8, 1.0, 1.0);
uniform float glow_strength : hint_range(0.0, 16.0) = 4.0;
uniform float rune_scale : hint_range(1.0, 32.0) = 8.0;
uniform float line_width : hint_range(0.01, 0.3) = 0.08;
uniform float pulse_speed : hint_range(0.0, 8.0) = 2.0;
uniform float roughness_value : hint_range(0.0, 1.0) = 0.7;

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void fragment() {
	vec2 g = UV * vec2(rune_scale * 2.0, rune_scale);
	vec2 id = floor(g);
	vec2 f = fract(g) - 0.5;
	float h = hash(id);
	// each cell gets a random mix of vertical, horizontal and diagonal strokes
	float d = 1.0;
	if (h > 0.2) d = min(d, abs(f.x));
	if (fract(h * 7.0) > 0.4) d = min(d, abs(f.y));
	if (fract(h * 13.0) > 0.6) d = min(d, abs(f.x - f.y) * 0.7071);
	if (fract(h * 29.0) > 0.7) d = min(d, abs(f.x + f.y) * 0.7071);
	float rune = 1.0 - smoothstep(line_width * 0.5, line_width, d);
	float pulse = 0.6 + 0.4 * sin(TIME * pulse_speed + h * 6.2831);
	ALBEDO = base_color.rgb;
	ROUGHNESS = roughness_value;
	EMISSION = glow_color.rgb * rune * pulse * glow_strength;
}
