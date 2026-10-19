// Dissolve Edge: noise-driven burn-away with a glowing rim. Drive dissolve_amount from code,
// or leave auto_speed > 0 to loop it for previews.
shader_type spatial;

uniform vec4 albedo_color : source_color = vec4(0.35, 0.3, 0.28, 1.0);
uniform vec4 edge_color : source_color = vec4(1.0, 0.45, 0.1, 1.0);
uniform float dissolve_amount : hint_range(0.0, 1.0) = 0.0;
uniform float auto_speed : hint_range(0.0, 2.0) = 0.5;
uniform float edge_width : hint_range(0.0, 0.2) = 0.05;
uniform float noise_scale : hint_range(1.0, 30.0) = 6.0;
uniform float emission_strength : hint_range(0.0, 16.0) = 6.0;

varying vec3 obj_pos;

float hash3(vec3 p) {
	return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

float noise3(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(
		mix(mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x), mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x), f.y),
		mix(mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x), mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x), f.y),
		f.z);
}

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	float n = noise3(obj_pos * noise_scale) * 0.65 + noise3(obj_pos * noise_scale * 2.3) * 0.35;
	float amount = auto_speed > 0.0 ? (0.5 - 0.5 * cos(TIME * auto_speed * 3.14159)) * 0.45 : dissolve_amount;
	if (n < amount) {
		discard;
	}
	float edge = 1.0 - smoothstep(amount, amount + edge_width, n);
	ALBEDO = albedo_color.rgb;
	ROUGHNESS = 0.8;
	EMISSION = edge_color.rgb * edge * emission_strength * step(0.001, amount);
}
