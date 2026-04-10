"use client";

import { useState } from "react";
import { Activity, AlertTriangle, Bot, Utensils } from "lucide-react";
import { generatePlan } from "@/lib/api";
import type { GeneratePlanResponse, UserProfile } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const initialProfile: UserProfile = {
  age: 29,
  gender: "male",
  weight: 72,
  height: 175,
  activity_level: "moderate",
  goal: "lean_loss",
  diet_type: "veg",
  medical_conditions: ["pcos"],
  allergies: [],
  food_preferences: ["indian", "high protein"],
  region: "indian"
};

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

export default function Home() {
  const [profile, setProfile] = useState<UserProfile>(initialProfile);
  const [message, setMessage] = useState("Generate a 4 meal Indian plan with high protein.");
  const [result, setResult] = useState<GeneratePlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      setResult(await generatePlan(profile, message));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate plan");
    } finally {
      setLoading(false);
    }
  }

  const totals = result?.plan?.daily_totals;
  const totalMacroCalories = totals ? totals.protein * 4 + totals.carbs * 4 + totals.fat * 9 : 1;

  return (
    <main className="min-h-screen bg-background px-4 py-6 text-text md:px-8">
      <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[420px_1fr]">
        <Card>
          <div className="mb-5 flex items-center gap-3">
            <Bot className="h-6 w-6 text-primary" />
            <div>
              <h1 className="text-2xl font-semibold">NutriBot</h1>
              <p className="text-sm text-muted">Validated nutrition planning</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm text-muted">
              Age
              <Input type="number" value={profile.age} onChange={(e) => setProfile({ ...profile, age: Number(e.target.value) })} />
            </label>
            <label className="text-sm text-muted">
              Gender
              <Select value={profile.gender} onChange={(e) => setProfile({ ...profile, gender: e.target.value as UserProfile["gender"] })}>
                <option value="male">Male</option>
                <option value="female">Female</option>
              </Select>
            </label>
            <label className="text-sm text-muted">
              Weight kg
              <Input type="number" value={profile.weight} onChange={(e) => setProfile({ ...profile, weight: Number(e.target.value) })} />
            </label>
            <label className="text-sm text-muted">
              Height cm
              <Input type="number" value={profile.height} onChange={(e) => setProfile({ ...profile, height: Number(e.target.value) })} />
            </label>
          </div>

          <div className="mt-3 grid gap-3">
            <label className="text-sm text-muted">
              Activity
              <Select value={profile.activity_level} onChange={(e) => setProfile({ ...profile, activity_level: e.target.value as UserProfile["activity_level"] })}>
                <option value="sedentary">Sedentary</option>
                <option value="light">Light</option>
                <option value="moderate">Moderate</option>
                <option value="active">Active</option>
                <option value="very_active">Very active</option>
              </Select>
            </label>
            <label className="text-sm text-muted">
              Goal
              <Select value={profile.goal} onChange={(e) => setProfile({ ...profile, goal: e.target.value as UserProfile["goal"] })}>
                <option value="fat_loss">Fat loss</option>
                <option value="lean_loss">Lean loss</option>
                <option value="maintenance">Maintenance</option>
                <option value="lean_bulk">Lean bulk</option>
                <option value="bulk">Bulk</option>
              </Select>
            </label>
            <label className="text-sm text-muted">
              Diet
              <Select value={profile.diet_type} onChange={(e) => setProfile({ ...profile, diet_type: e.target.value as UserProfile["diet_type"] })}>
                <option value="veg">Veg</option>
                <option value="non_veg">Non veg</option>
                <option value="vegan">Vegan</option>
              </Select>
            </label>
            <label className="text-sm text-muted">
              Medical conditions
              <Input value={profile.medical_conditions.join(", ")} onChange={(e) => setProfile({ ...profile, medical_conditions: splitList(e.target.value) })} />
            </label>
            <label className="text-sm text-muted">
              Allergies
              <Input value={profile.allergies.join(", ")} onChange={(e) => setProfile({ ...profile, allergies: splitList(e.target.value) })} />
            </label>
            <label className="text-sm text-muted">
              Preferences
              <Input value={profile.food_preferences.join(", ")} onChange={(e) => setProfile({ ...profile, food_preferences: splitList(e.target.value) })} />
            </label>
            <label className="text-sm text-muted">
              Region
              <Input value={profile.region ?? ""} onChange={(e) => setProfile({ ...profile, region: e.target.value })} />
            </label>
            <label className="text-sm text-muted">
              Chat request
              <Textarea value={message} onChange={(e) => setMessage(e.target.value)} />
            </label>
            <Button disabled={loading} onClick={submit}>
              {loading ? "Validating..." : "Generate Plan"}
            </Button>
          </div>
        </Card>

        <section className="grid gap-5">
          <div className="grid gap-5 md:grid-cols-3">
            <Card>
              <Activity className="mb-3 h-5 w-5 text-primary" />
              <p className="text-sm text-muted">Calories</p>
              <p className="text-2xl font-semibold">{result?.targets.target_calories ?? "--"}</p>
            </Card>
            <Card>
              <Utensils className="mb-3 h-5 w-5 text-primary" />
              <p className="text-sm text-muted">Protein</p>
              <p className="text-2xl font-semibold">{result?.targets.protein_target ?? "--"} g</p>
            </Card>
            <Card>
              <p className="text-sm text-muted">Status</p>
              <p className="mt-3 text-2xl font-semibold">{result?.status ?? "Ready"}</p>
            </Card>
          </div>

          {error ? (
            <Card className="border-[#b45309] bg-[#24170b]">
              <div className="flex items-center gap-2 text-[#fbbf24]">
                <AlertTriangle className="h-5 w-5" />
                <span>{error}</span>
              </div>
            </Card>
          ) : null}

          {totals ? (
            <Card>
              <h2 className="mb-4 text-xl font-semibold">Macros</h2>
              {[
                ["Protein", totals.protein * 4, `${totals.protein} g`],
                ["Carbs", totals.carbs * 4, `${totals.carbs} g`],
                ["Fat", totals.fat * 9, `${totals.fat} g`]
              ].map(([label, calories, value]) => (
                <div key={label as string} className="mb-3">
                  <div className="mb-1 flex justify-between text-sm text-muted">
                    <span>{label}</span>
                    <span>{value}</span>
                  </div>
                  <div className="h-3 rounded-lg bg-panel">
                    <div className="h-3 rounded-lg bg-primary" style={{ width: `${Math.min(100, (Number(calories) / totalMacroCalories) * 100)}%` }} />
                  </div>
                </div>
              ))}
            </Card>
          ) : null}

          {result?.validation_errors.length ? (
            <Card className="border-[#b45309]">
              <h2 className="mb-3 text-lg font-semibold">Validation</h2>
              {result.validation_errors.map((item) => (
                <p key={item} className="text-sm text-[#fbbf24]">{item}</p>
              ))}
            </Card>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            {result?.plan?.meals.map((meal) => (
              <Card key={meal.name}>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-lg font-semibold">{meal.name}</h2>
                  <span className="text-sm text-muted">{meal.total_calories} kcal</span>
                </div>
                <div className="grid gap-3">
                  {meal.items.map((item) => (
                    <div key={`${meal.name}-${item.food}`} className="rounded-lg border border-border bg-panel p-3">
                      <div className="flex justify-between gap-3">
                        <p className="font-medium">{item.food}</p>
                        <p className="text-sm text-muted">{item.quantity}</p>
                      </div>
                      <p className="mt-1 text-sm text-muted">
                        {item.calories} kcal | P {item.protein} | C {item.carbs} | F {item.fat}
                      </p>
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
