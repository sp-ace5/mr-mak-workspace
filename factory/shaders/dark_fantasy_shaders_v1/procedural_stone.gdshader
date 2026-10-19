// Procedural Stone: object-space fbm stone with dark cracks and faint glowing veins. No textures,
// so no UV seams on any mesh.
shader_type spatial;

uniform vec4 stone_light : source_color = vec4(0.42, 0.4, 0.38, 1.0);
uniform vec4 stone_dark : source_color = vec4(0.16, 0.15, 0.15, 1.0);
uniform vec4 vein_color : source_color = vec4(0.6, 0.15, 0.9, 1.0);
uniform float stone_scale : hint_range(0.5, 20.0) = 4.0;
uniform float crack_width : hint_range(0.0, 0.1) = 0.03;
uniform float vein_strength : hint_range(0.0, 8.0) = 1.5;
uniform float vein_pulse_speed : hint_range(0.0, 4.0) = 1.0;
uniform float roughness_value : hint_range(0.0, 1.0) = 0.9;

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

float fbm(vec3 p) {
	float v = 0.0;
	float a = 0.5;
	for (int i = 0; i < 5; i++) {
		v += a * noise3(p);
		p *= 2.03;
		a *= 0.5;
	}
	return v;
}

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	vec3 p = obj_pos * stone_scale;
	float base = fbm(p);
	float ridge = abs(fbm(p * 0.7 + 11.0) - 0.5);          // ~0 along crack lines
	float crack = 1.0 - smoothstep(0.0, crack_width, ridge);
	ALBEDO = mix(stone_dark.rgb, stone_light.rgb, base) * (1.0 - crack * 0.8);
	ROUGHNESS = roughness_value;
	float pulse = 0.5 + 0.5 * sin(TIME * vein_pulse_speed + base * 6.2831);
	EMISSION = vein_color.rgb * crack * pulse * vein_strength;
}
