"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createProfile, type ProfilePayload } from "@/src/services/api";

const STEPS = ["Personal", "Health", "Lifestyle", "Personalize"] as const;

const MEDICAL_OPTIONS = [
  "Type 2 Diabetes",
  "PCOS",
  "Hypothyroidism",
  "Hypertension",
  "CKD",
];
const ALLERGY_OPTIONS = [
  "Gluten",
  "Milk",
  "Eggs",
  "Nuts",
  "Soy",
  "Shellfish",
  "Fish",
];

function MultiSelect({
  options,
  selected,
  onChange,
}: {
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  function toggle(opt: string) {
    onChange(
      selected.includes(opt)
        ? selected.filter((s) => s !== opt)
        : [...selected, opt]
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => toggle(opt)}
          className={`px-3 py-1.5 rounded-lg text-sm border transition-colors
            ${selected.includes(opt)
              ? "bg-primary text-background border-primary"
              : "bg-panel border-border text-muted hover:border-primary hover:text-text"
            }`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm text-muted mb-1.5">{label}</label>
      {children}
    </div>
  );
}

function StyledInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full bg-panel border border-border rounded-xl px-4 py-2.5 text-text text-sm
        placeholder:text-muted focus:outline-none focus:border-primary transition-colors"
    />
  );
}

function StyledSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="w-full bg-panel border border-border rounded-xl px-4 py-2.5 text-text text-sm
        focus:outline-none focus:border-primary transition-colors appearance-none"
    />
  );
}

export default function ProfileBuilderPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [form, setForm] = useState({
    full_name: "",
    gender: "male",
    age: "",
    height_cm: "",
    weight_kg: "",
    height_unit: "cm",
    weight_unit: "kg",
    medical_conditions: [] as string[],
    allergies: [] as string[],
    custom_conditions: "",
    custom_allergies: "",
    medications: "",
    activity_level: "moderately_active",
    diet_type: "non_vegetarian",
    goal: "maintenance",
    bot_name: "Nova",
  });

  function set(key: string, value: unknown) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit() {
    setError(null);
    setLoading(true);
    try {
      const conditions = [
        ...form.medical_conditions,
        ...form.custom_conditions
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      ];
      const allergies = [
        ...form.allergies,
        ...form.custom_allergies
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      ];

      let height = parseFloat(form.height_cm);
      let weight = parseFloat(form.weight_kg);

      // Convert units if needed
      if (form.height_unit === "ft_in") {
        // Expect "5'11" format
        const match = form.height_cm.match(/(\d+)'(\d+)/);
        if (match) {
          height = parseInt(match[1]) * 30.48 + parseInt(match[2]) * 2.54;
        }
      }
      if (form.weight_unit === "lbs") {
        weight = weight * 0.453592;
      }

      const payload: ProfilePayload = {
        full_name: form.full_name,
        gender: form.gender,
        age: parseInt(form.age),
        height_cm: Math.round(height),
        weight_kg: Math.round(weight * 10) / 10,
        medical_conditions: conditions,
        allergies,
        medications: form.medications || undefined,
        activity_level: form.activity_level,
        diet_type: form.diet_type,
        goal: form.goal,
        bot_name: form.bot_name,
      };

      const user = await createProfile(payload);
      localStorage.setItem("nutribot_user", JSON.stringify(user));
      router.push("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setLoading(false);
    }
  }

  const isLastStep = step === STEPS.length - 1;

  return (
    <main className="min-h-screen bg-background flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-lg">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-text">Build Your Profile</h1>
          <p className="text-muted text-sm mt-1">
            Help us personalize your nutrition journey
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6">
          {STEPS.map((s, i) => (
            <div key={s} className="flex-1 flex flex-col items-center gap-1">
              <div
                className={`w-full h-1.5 rounded-full transition-colors ${
                  i <= step ? "bg-primary" : "bg-panel"
                }`}
              />
              <span
                className={`text-xs ${
                  i === step ? "text-primary font-medium" : "text-muted"
                }`}
              >
                {s}
              </span>
            </div>
          ))}
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6">
          {/* Step 0 — Personal */}
          {step === 0 && (
            <div className="space-y-4">
              <Field label="Full Name">
                <StyledInput
                  value={form.full_name}
                  onChange={(e) => set("full_name", e.target.value)}
                  placeholder="Your full name"
                />
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Gender">
                  <StyledSelect
                    value={form.gender}
                    onChange={(e) => set("gender", e.target.value)}
                  >
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                    <option value="other">Other</option>
                  </StyledSelect>
                </Field>
                <Field label="Age">
                  <StyledInput
                    type="number"
                    value={form.age}
                    onChange={(e) => set("age", e.target.value)}
                    placeholder="Years"
                    min={13}
                    max={100}
                  />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Field label={`Height (${form.height_unit === "cm" ? "cm" : "ft'in"})`}>
                  <div className="flex gap-2">
                    <StyledInput
                      value={form.height_cm}
                      onChange={(e) => set("height_cm", e.target.value)}
                      placeholder={form.height_unit === "cm" ? "170" : "5'11"}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        set(
                          "height_unit",
                          form.height_unit === "cm" ? "ft_in" : "cm"
                        )
                      }
                      className="px-2 text-xs text-primary border border-border rounded-lg whitespace-nowrap"
                    >
                      {form.height_unit === "cm" ? "ft" : "cm"}
                    </button>
                  </div>
                </Field>
                <Field label={`Weight (${form.weight_unit})`}>
                  <div className="flex gap-2">
                    <StyledInput
                      type="number"
                      value={form.weight_kg}
                      onChange={(e) => set("weight_kg", e.target.value)}
                      placeholder={form.weight_unit === "kg" ? "70" : "154"}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        set(
                          "weight_unit",
                          form.weight_unit === "kg" ? "lbs" : "kg"
                        )
                      }
                      className="px-2 text-xs text-primary border border-border rounded-lg"
                    >
                      {form.weight_unit === "kg" ? "lbs" : "kg"}
                    </button>
                  </div>
                </Field>
              </div>
            </div>
          )}

          {/* Step 1 — Health */}
          {step === 1 && (
            <div className="space-y-5">
              <Field label="Medical Conditions (select all that apply)">
                <MultiSelect
                  options={MEDICAL_OPTIONS}
                  selected={form.medical_conditions}
                  onChange={(v) => set("medical_conditions", v)}
                />
                <StyledInput
                  className="mt-2"
                  value={form.custom_conditions}
                  onChange={(e) => set("custom_conditions", e.target.value)}
                  placeholder="Other conditions, comma-separated"
                />
              </Field>
              <Field label="Food Allergies (select all that apply)">
                <MultiSelect
                  options={ALLERGY_OPTIONS}
                  selected={form.allergies}
                  onChange={(v) => set("allergies", v)}
                />
                <StyledInput
                  className="mt-2"
                  value={form.custom_allergies}
                  onChange={(e) => set("custom_allergies", e.target.value)}
                  placeholder="Other allergies, comma-separated"
                />
              </Field>
              <Field label="Current Medications (optional)">
                <StyledInput
                  value={form.medications}
                  onChange={(e) => set("medications", e.target.value)}
                  placeholder="e.g. Metformin 500mg, Levothyroxine"
                />
              </Field>
            </div>
          )}

          {/* Step 2 — Lifestyle */}
          {step === 2 && (
            <div className="space-y-4">
              <Field label="Daily Activity Level">
                <StyledSelect
                  value={form.activity_level}
                  onChange={(e) => set("activity_level", e.target.value)}
                >
                  <option value="sedentary">Sedentary (desk job, no exercise)</option>
                  <option value="lightly_active">Lightly Active (1-3 days/week)</option>
                  <option value="moderately_active">Moderately Active (3-5 days/week)</option>
                  <option value="very_active">Very Active (6-7 days/week)</option>
                  <option value="extremely_active">Extremely Active (athlete / physical job)</option>
                </StyledSelect>
              </Field>
              <Field label="Dietary Preference">
                <StyledSelect
                  value={form.diet_type}
                  onChange={(e) => set("diet_type", e.target.value)}
                >
                  <option value="non_vegetarian">Non-Vegetarian</option>
                  <option value="vegetarian">Vegetarian</option>
                  <option value="vegan">Vegan</option>
                </StyledSelect>
              </Field>
              <Field label="Health Goal">
                <StyledSelect
                  value={form.goal}
                  onChange={(e) => set("goal", e.target.value)}
                >
                  <option value="fat_loss">Fat Loss</option>
                  <option value="weight_gain">Weight Gain</option>
                  <option value="muscle_gain">Muscle Gain</option>
                  <option value="maintenance">Maintenance</option>
                  <option value="manage_medical">Manage Medical Condition</option>
                </StyledSelect>
              </Field>
            </div>
          )}

          {/* Step 3 — Personalize */}
          {step === 3 && (
            <div className="space-y-4">
              <Field label="Name your NutriBot">
                <StyledInput
                  value={form.bot_name}
                  onChange={(e) => set("bot_name", e.target.value)}
                  placeholder="e.g. Nova, Max, Zara"
                />
                <p className="text-xs text-muted mt-1.5">
                  Your bot will use this name in all conversations.
                </p>
              </Field>

              <div className="bg-panel border border-border rounded-xl p-4 text-sm text-muted space-y-1 mt-2">
                <p>
                  <span className="text-text font-medium">Bot Name:</span>{" "}
                  {form.bot_name || "Nova"}
                </p>
                <p>
                  <span className="text-text font-medium">Goal:</span>{" "}
                  {form.goal.replace("_", " ")}
                </p>
                <p>
                  <span className="text-text font-medium">Diet:</span>{" "}
                  {form.diet_type.replace("_", " ")}
                </p>
                {form.medical_conditions.length > 0 && (
                  <p>
                    <span className="text-text font-medium">Conditions:</span>{" "}
                    {form.medical_conditions.join(", ")}
                  </p>
                )}
              </div>
            </div>
          )}

          {error && (
            <p className="mt-4 text-sm text-red-400 bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {/* Navigation */}
          <div className="flex gap-3 mt-6">
            {step > 0 && (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                className="flex-1 bg-panel border border-border text-text rounded-xl py-2.5 text-sm
                  hover:bg-border transition-colors"
              >
                ← Back
              </button>
            )}
            <button
              type="button"
              onClick={isLastStep ? submit : () => setStep(step + 1)}
              disabled={loading}
              className="flex-1 bg-primary text-background font-semibold rounded-xl py-2.5 text-sm
                hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading
                ? "Saving…"
                : isLastStep
                ? "Start Chatting 🚀"
                : "Continue →"}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
