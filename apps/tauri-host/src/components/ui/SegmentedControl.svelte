<script lang="ts" generics="T extends string">
  import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

  type SegmentedOption<T extends string> = {
    id: T;
    label: string;
    disabled?: boolean;
  };

  interface Props {
    options: SegmentedOption<T>[];
    value: T;
    ariaLabel?: string;
    disabled?: boolean;
    onValueChange: (value: T) => void;
  }

  let { options, value, ariaLabel, disabled = false, onValueChange }: Props = $props();
</script>

<!-- 分段选择器：基于 shadcn ToggleGroup，样式沿用项目 token（单行等宽、选中蓝底） -->
<ToggleGroup
  type="single"
  {value}
  {disabled}
  aria-label={ariaLabel}
  onValueChange={(next) => {
    if (typeof next === "string" && next) onValueChange(next as T);
  }}
  class="segmented"
>
  {#each options as option (option.id)}
    <ToggleGroupItem value={option.id} disabled={disabled || option.disabled} class="segmented-item data-[state=on]:bg-[var(--surface-strong)] data-[state=on]:text-[var(--accent)]">
      {option.label}
    </ToggleGroupItem>
  {/each}
</ToggleGroup>
