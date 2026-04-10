export type UserProfile = {
  age: number;
  gender: "male" | "female";
  weight: number;
  height: number;
  activity_level: "sedentary" | "light" | "moderate" | "active" | "very_active";
  goal: "fat_loss" | "lean_loss" | "maintenance" | "lean_bulk" | "bulk";
  diet_type: "veg" | "non_veg" | "vegan";
  medical_conditions: string[];
  allergies: string[];
  food_preferences: string[];
  region?: string | null;
};

export type MealItem = {
  food: string;
  quantity: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

export type MealPlan = {
  meals: Array<{
    name: string;
    items: MealItem[];
    total_calories: number;
  }>;
  daily_totals: {
    calories: number;
    protein: number;
    carbs: number;
    fat: number;
  };
};

export type GeneratePlanResponse = {
  status: "ok" | "error";
  targets: {
    bmr: number;
    tdee: number;
    target_calories: number;
    protein_target: number;
  };
  cag_context: unknown;
  retrieved_knowledge: string[];
  plan: MealPlan | null;
  validation_errors: string[];
};
