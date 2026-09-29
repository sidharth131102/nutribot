"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { ContactShadows, Float, MeshDistortMaterial, Sparkles } from "@react-three/drei";
import { Suspense, useEffect, useRef } from "react";
import { DoubleSide } from "three";
import type * as THREE from "three";

// Small "food" spheres mounded in the bowl -- position, radius, color,
// surface roughness (glossy cherry vs. matte citrus), and whether it gets a
// tiny stem nub. Fixed (not random) so the composition is stable and
// deliberate rather than occasionally overlapping oddly.
const FOOD_ITEMS: { pos: [number, number, number]; r: number; color: string; roughness: number; stem?: boolean; leaf?: boolean; squash?: number }[] = [
  { pos: [0, 0.6, 0], r: 0.32, color: "#8fce2e", roughness: 0.35, stem: true, leaf: true, squash: 0.94 },
  { pos: [-0.44, 0.46, 0.2], r: 0.24, color: "#ff6b4a", roughness: 0.15, stem: true },
  { pos: [0.42, 0.46, -0.2], r: 0.26, color: "#f5c518", roughness: 0.5 },
  { pos: [0.08, 0.38, 0.44], r: 0.22, color: "#d64545", roughness: 0.3, stem: true, leaf: true, squash: 0.95 },
  { pos: [-0.3, 0.36, -0.42], r: 0.2, color: "#e0503a", roughness: 0.15, stem: true },
  { pos: [0.46, 0.58, 0.32], r: 0.16, color: "#d6f83c", roughness: 0.2, stem: true },
];

/** A bowl heaped with colorful food -- easier to render convincingly with
 *  plain primitives than a single sculpted fruit (an apple built from
 *  spheres read as "two blobs stuck together," not a fruit), and a bowl of
 *  food maps directly onto "meal planning" rather than a generic object.
 *  Each piece gets a faint organic distort (not a perfect sphere) and its
 *  own roughness -- glossy for cherry-like fruit, matte for citrus -- plus a
 *  tiny stem nub on a few, so they read as fruit rather than balls. */
function FoodBowl() {
  const groupRef = useRef<THREE.Group>(null);
  const foodRefs = useRef<(THREE.Group | null)[]>([]);

  useFrame((state) => {
    const t = state.clock.getElapsedTime();
    if (groupRef.current) groupRef.current.rotation.y = t * 0.18;
    foodRefs.current.forEach((g, i) => {
      if (g) g.position.y = FOOD_ITEMS[i].pos[1] + Math.sin(t * 1.3 + i * 1.7) * 0.02;
    });
  });

  return (
    <group ref={groupRef}>
      {/* Bowl outer wall -- gives the rim real thickness instead of a paper-thin edge */}
      <mesh rotation={[Math.PI, 0, 0]} position={[0, -0.05, 0]} scale={1.04} castShadow>
        <sphereGeometry args={[1.15, 48, 32, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color="#e9e8df" roughness={0.7} side={DoubleSide} />
      </mesh>
      {/* Bowl interior -- the lower half of a sphere shell, seen from above */}
      <mesh rotation={[Math.PI, 0, 0]} position={[0, -0.05, 0]} receiveShadow>
        <sphereGeometry args={[1.15, 48, 32, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color="#f7f6f0" roughness={0.55} metalness={0.02} side={DoubleSide} />
      </mesh>
      {/* Bowl rim -- the black outline that ties it to the rest of the brand */}
      <mesh position={[0, -0.05, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <torusGeometry args={[1.15, 0.055, 16, 64]} />
        <meshStandardMaterial color="#111111" roughness={0.45} />
      </mesh>

      {/* Food, mounded above the rim -- apple/tomato-like items (stem+leaf)
          are scaled slightly flatter top-to-bottom, the way real fruit
          isn't a perfect sphere; citrus/cherries stay round. */}
      {FOOD_ITEMS.map((item, i) => (
        <group key={i} ref={(el) => { foodRefs.current[i] = el; }} position={item.pos}>
          <mesh castShadow receiveShadow scale={[1, item.squash ?? 1, 1]}>
            <sphereGeometry args={[item.r, 32, 32]} />
            <MeshDistortMaterial color={item.color} roughness={item.roughness} metalness={0.05} distort={0.05} speed={1} />
          </mesh>
          {item.stem && (
            <mesh position={[0, item.r * (item.squash ?? 1) * 0.95, 0]} rotation={[0, 0, 0.15]}>
              <cylinderGeometry args={[0.014, 0.02, item.r * 0.45, 6]} />
              <meshStandardMaterial color="#3a2a1a" roughness={0.7} />
            </mesh>
          )}
          {item.leaf && (
            <mesh
              position={[item.r * 0.35, item.r * (item.squash ?? 1) * 0.98, 0]}
              rotation={[0.3, 0.5, 0.6]}
              scale={[item.r * 0.9, item.r * 0.42, item.r * 0.1]}
            >
              <sphereGeometry args={[1, 16, 16]} />
              <meshStandardMaterial color="#4a8f3c" roughness={0.4} />
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
}

/** Tracks the pointer and gently steers the whole rig toward it -- the
 *  parallax that makes the scene feel like it's actually in the room. */
function PointerRig({ children }: { children: React.ReactNode }) {
  const groupRef = useRef<THREE.Group>(null);
  const target = useRef({ x: 0, y: 0 });

  useEffect(() => {
    function handlePointerMove(e: PointerEvent) {
      target.current.x = (e.clientX / window.innerWidth - 0.5) * 0.5;
      target.current.y = (e.clientY / window.innerHeight - 0.5) * -0.25;
    }
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", handlePointerMove);
  }, []);

  useFrame(() => {
    if (!groupRef.current) return;
    groupRef.current.rotation.y += (target.current.x - groupRef.current.rotation.y) * 0.04;
    groupRef.current.rotation.x += (target.current.y - groupRef.current.rotation.x) * 0.04;
  });

  return <group ref={groupRef}>{children}</group>;
}

export default function HeroOrb() {
  return (
    <Canvas
      shadows
      dpr={[1, 1.75]}
      camera={{ position: [0, 0.15, 6.8], fov: 34 }}
      gl={{ antialias: true, alpha: true }}
      style={{ width: "100%", height: "100%" }}
    >
      <Suspense fallback={null}>
        <ambientLight intensity={0.7} />
        <directionalLight
          position={[3, 5, 4]}
          intensity={2.2}
          color="#ffffff"
          castShadow
          shadow-mapSize={[1024, 1024]}
        />
        <pointLight position={[-4, -1, -3]} intensity={18} color="#ff6b4a" />
        <PointerRig>
          <Float speed={1.4} rotationIntensity={0.3} floatIntensity={0.7}>
            <FoodBowl />
          </Float>
        </PointerRig>
        <ContactShadows position={[0, -0.9, 0]} opacity={0.35} scale={4} blur={2.4} far={1.5} color="#111111" />
        <Sparkles count={40} scale={4.2} size={2.4} speed={0.25} color="#111111" opacity={0.3} />
      </Suspense>
    </Canvas>
  );
}
