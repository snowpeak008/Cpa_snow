import { cn } from "cn";

// Sliding segmented control. shadcn/radix has no official equivalent
// (Tabs only offers an underline variant), so the range picker and the
// bucket switcher share this single implementation.
export function SegmentedControl({
  items,
  value,
  onChange,
  ariaLabel,
  className,
}) {
  const activeIndex = items.findIndex((item) => item.value === value);
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn(
        "relative grid w-fit rounded-md bg-muted p-[3px]",
        className,
      )}
      style={{
        gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`,
      }}
    >
      {activeIndex >= 0 && (
        <span
          aria-hidden
          className="absolute inset-y-[3px] left-[3px] rounded-[5px] bg-background shadow-sm transition-transform duration-300 ease-out"
          style={{
            width: `calc((100% - 6px) / ${items.length})`,
            transform: `translateX(${activeIndex * 100}%)`,
          }}
        />
      )}
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          aria-pressed={item.value === value}
          className={cn(
            "relative z-10 inline-flex h-7 items-center justify-center gap-1.5 rounded-[5px] px-3 text-sm transition-colors",
            item.value === value
              ? "font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
