"use client";

type MealItem = {
  food: string;
  quantity: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
};

type Meal = {
  name: string;
  items: MealItem[];
  total_calories: number;
};

type DayPlan = {
  day: string;
  meals: Meal[];
  daily_totals: {
    calories: number;
    protein: number;
    carbs: number;
    fat: number;
  };
};

type Props = {
  plan: {
    days: DayPlan[];
    calorie_target: number;
    macro_targets: { protein_g: number; carbs_g: number; fat_g: number };
    daily_routine?: string;
  };
};

export default function MealPlanCard({ plan }: Props) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-text">7-Day Meal Plan</h3>
        <span className="text-sm text-muted">
          Target: {plan.calorie_target} kcal/day
        </span>
      </div>

      <div className="flex gap-3 text-sm">
        <span className="bg-panel border border-border rounded-lg px-3 py-1 text-primary">
          P {plan.macro_targets.protein_g}g
        </span>
        <span className="bg-panel border border-border rounded-lg px-3 py-1 text-primary">
          C {plan.macro_targets.carbs_g}g
        </span>
        <span className="bg-panel border border-border rounded-lg px-3 py-1 text-primary">
          F {plan.macro_targets.fat_g}g
        </span>
      </div>

      <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
        {plan.days.map((day) => (
          <details key={day.day} className="group">
            <summary className="cursor-pointer list-none flex items-center justify-between bg-panel rounded-lg px-3 py-2 hover:bg-border transition-colors">
              <span className="font-medium text-text text-sm">{day.day}</span>
              <span className="text-muted text-xs">
                {day.daily_totals?.calories ?? 0} kcal
                <span className="ml-2 text-primary group-open:rotate-180 inline-block transition-transform">▾</span>
              </span>
            </summary>
            <div className="mt-2 ml-2 space-y-2">
              {day.meals.map((meal) => (
                <div key={meal.name} className="border border-border rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between bg-panel px-3 py-1.5">
                    <span className="text-sm font-medium text-primary">{meal.name}</span>
                    <span className="text-xs text-muted">{meal.total_calories} kcal</span>
                  </div>
                  <div className="divide-y divide-border">
                    {meal.items.map((item, idx) => (
                      <div key={idx} className="px-3 py-1.5 text-xs">
                        <div className="flex justify-between text-text">
                          <span>{item.food}</span>
                          <span className="text-muted">{item.quantity}</span>
                        </div>
                        <div className="text-muted mt-0.5">
                          {item.calories} kcal | P {item.protein}g · C {item.carbs}g · F {item.fat}g
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>

      {plan.daily_routine && (
        <div className="border-t border-border pt-3">
          <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-1">Daily Routine</p>
          <p className="text-sm text-text whitespace-pre-line">{plan.daily_routine}</p>
        </div>
      )}
    </div>
  );
}
