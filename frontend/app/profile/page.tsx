"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createProfile,
  getConsentStatus,
  getMyProfile,
  getSpokenLanguages,
  grantConsent,
  updateProfile,
  type AuthUser,
  type ProfilePayload,
  type SpokenLanguagesResponse,
} from "@/src/services/api";
import { resetSpeechToken } from "@/src/services/speech";

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

const EMPTY_FORM = {
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
  spoken_languages: [] as string[],
};

/** Split stored values into "known option" chips and a free-text remainder,
 *  so an existing profile round-trips through the same two controls. */
function splitKnown(values: string[], options: string[]) {
  const lookup = new Map(options.map((o) => [o.toLowerCase(), o]));
  const known: string[] = [];
  const custom: string[] = [];
  for (const v of values) {
    const match = lookup.get(v.toLowerCase());
    if (match) known.push(match);
    else custom.push(v);
  }
  return { known, custom: custom.join(", ") };
}

function formFromProfile(user: AuthUser): typeof EMPTY_FORM {
  const conditions = splitKnown(user.medical_conditions ?? [], MEDICAL_OPTIONS);
  const allergies = splitKnown(user.allergies ?? [], ALLERGY_OPTIONS);
  return {
    ...EMPTY_FORM,
    full_name: user.full_name ?? "",
    gender: user.gender ?? "male",
    age: user.age != null ? String(user.age) : "",
    height_cm: user.height_cm != null ? String(user.height_cm) : "",
    weight_kg: user.weight_kg != null ? String(user.weight_kg) : "",
    medical_conditions: conditions.known,
    custom_conditions: conditions.custom,
    allergies: allergies.known,
    custom_allergies: allergies.custom,
    medications: user.medications ?? "",
    activity_level: user.activity_level ?? "moderately_active",
    diet_type: user.diet_type ?? "non_vegetarian",
    goal: user.goal ?? "maintenance",
    bot_name: user.bot_name || "Nova",
    spoken_languages: user.spoken_languages ?? [],
  };
}

export default function ProfileBuilderPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Edit mode: the user already has a complete profile and came here from
  // the chat page to change something (or just to rename the bot).
  const [editMode, setEditMode] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [consentGranted, setConsentGranted] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  // Voice-input language options; null while loading or if the server has
  // no voice support (the selector simply doesn't render then).
  const [spokenOptions, setSpokenOptions] = useState<SpokenLanguagesResponse | null>(null);

  const [form, setForm] = useState(EMPTY_FORM);

  useEffect(() => {
    const token = localStorage.getItem("nutribot_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    const stored = localStorage.getItem("nutribot_user");
    const cached: AuthUser | null = stored ? JSON.parse(stored) : null;
    const requestedStep = parseInt(new URLSearchParams(window.location.search).get("step") ?? "", 10);

    async function init() {
      try {
        if (cached?.profile_complete) {
          const fresh = await getMyProfile();
          setForm(formFromProfile(fresh));
          setEditMode(true);
          localStorage.setItem("nutribot_user", JSON.stringify(fresh));
          if (!Number.isNaN(requestedStep) && requestedStep >= 0 && requestedStep < STEPS.length) {
            setStep(requestedStep);
          }
        } else if (cached?.full_name) {
          setForm((prev) => ({ ...prev, full_name: cached.full_name }));
        }
        try {
          const consent = await getConsentStatus();
          setConsentGranted(consent.granted);
          setConsentChecked(consent.granted);
        } catch {
          // No consent record yet -- treated as not granted.
        }
        try {
          setSpokenOptions(await getSpokenLanguages());
        } catch {
          // Older backend or voice not deployed -- hide the selector.
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load your profile");
      } finally {
        setInitializing(false);
      }
    }
    init();
  }, [router]);

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

      if (conditions.length > 0 && !consentChecked) {
        setStep(1);
        throw new Error(
          "Please confirm the medical-data consent on the Health step to save medical conditions."
        );
      }

      const payload: ProfilePayload = {
        full_name: form.full_name.trim(),
        gender: form.gender,
        age: parseInt(form.age),
        height_cm: Math.round(height),
        weight_kg: Math.round(weight * 10) / 10,
        medical_conditions: conditions,
        allergies,
        // In edit mode an empty string clears a previously stored value;
        // the backend skips only `null`/absent fields.
        medications: editMode ? form.medications : form.medications || undefined,
        activity_level: form.activity_level,
        diet_type: form.diet_type,
        goal: form.goal,
        bot_name: form.bot_name.trim() || "Nova",
        spoken_languages: form.spoken_languages,
      };

      // The backend refuses to store medical conditions without recorded
      // consent (403), so grant it first when the user has ticked the box.
      if (conditions.length > 0 && consentChecked && !consentGranted) {
        await grantConsent();
        setConsentGranted(true);
      }

      const user = editMode ? await updateProfile(payload) : await createProfile(payload);
      localStorage.setItem("nutribot_user", JSON.stringify(user));
      resetSpeechToken(); // the mic's language list rides on the token
      router.push("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setLoading(false);
    }
  }

  const isLastStep = step === STEPS.length - 1;
  const hasConditions =
    form.medical_conditions.length > 0 || form.custom_conditions.trim().length > 0;

  if (initializing) {
    return (
      <main className="min-h-screen bg-background flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-background flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-lg">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-text">
            {editMode ? "Edit Your Profile" : "Build Your Profile"}
          </h1>
          <p className="text-muted text-sm mt-1">
            {editMode
              ? "Changes apply to every plan and answer from now on"
              : "Help us personalize your nutrition journey"}
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6">
          {STEPS.map((s, i) => (
            <button
              key={s}
              type="button"
              // In edit mode every step is already filled in, so let the
              // user jump straight to the one they came to change.
              onClick={() => editMode && setStep(i)}
              disabled={!editMode}
              className="flex-1 flex flex-col items-center gap-1 disabled:cursor-default"
            >
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
            </button>
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
              {hasConditions && (
                <label className="flex items-start gap-3 bg-panel border border-border rounded-xl p-3 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={consentChecked}
                    onChange={(e) => setConsentChecked(e.target.checked)}
                    className="mt-0.5 accent-primary"
                  />
                  <span className="text-muted">
                    I consent to NutriBot storing my medical conditions and using them to
                    personalise nutrition guidance. This is required to save conditions
                    {consentGranted && (
                      <span className="text-primary"> · already on record</span>
                    )}
                    .
                  </span>
                </label>
              )}
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

              {spokenOptions && (
                <Field label={`Languages you speak (for voice input, up to ${spokenOptions.max_selectable})`}>
                  <MultiSelect
                    options={spokenOptions.supported.map((o) => o.label)}
                    selected={form.spoken_languages
                      .map((code) => spokenOptions.supported.find((o) => o.code === code)?.label)
                      .filter((l): l is string => Boolean(l))}
                    onChange={(labels) => {
                      const codes = labels
                        .map((label) => spokenOptions.supported.find((o) => o.label === label)?.code)
                        .filter((c): c is string => Boolean(c));
                      // One variant per language (en-IN and en-US can't both be
                      // listened for) and at most max_selectable -- the same
                      // rules the backend enforces, applied early for feedback.
                      const bases = new Set<string>();
                      const deduped = codes.filter((c) => {
                        const base = c.split("-")[0];
                        if (bases.has(base)) return false;
                        bases.add(base);
                        return true;
                      });
                      set("spoken_languages", deduped.slice(-spokenOptions.max_selectable));
                    }}
                  />
                  <p className="text-xs text-muted mt-1.5">
                    The microphone auto-detects between these when you speak.{" "}
                    {form.spoken_languages.length === 0
                      ? `Leave empty to use the default (${spokenOptions.default
                          .map((code) => spokenOptions.supported.find((o) => o.code === code)?.label ?? code)
                          .join(", ")}).`
                      : "Pick just one for the most accurate recognition."}
                  </p>
                </Field>
              )}

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
            {editMode && !isLastStep && (
              <button
                type="button"
                onClick={submit}
                disabled={loading}
                className="flex-1 bg-panel border border-primary/40 text-primary rounded-xl py-2.5 text-sm
                  hover:bg-border disabled:opacity-50 transition-colors"
              >
                {loading ? "Saving…" : "Save Changes"}
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
                ? editMode
                  ? "Save Changes"
                  : "Start Chatting 🚀"
                : "Continue →"}
            </button>
          </div>
          {editMode && (
            <button
              type="button"
              onClick={() => router.push("/chat")}
              className="w-full mt-3 text-xs text-muted hover:text-text transition-colors"
            >
              Cancel and go back to chat
            </button>
          )}
        </div>
      </div>
    </main>
  );
}
