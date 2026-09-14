<script lang="ts" generics="T extends string">
  import * as Select from "@/components/ui/select";
  import { cn } from "@/utils.js";

  type Option<T extends string> = { value: T; label: string; disabled?: boolean };

  interface Props {
    options: readonly Option<T>[];
    value: T;
    placeholder?: string;
    ariaLabel: string;
    disabled?: boolean;
    size?: "sm" | "default";
    className?: string;
    onValueChange: (value: T) => void;
  }

  let {
    options,
    value,
    placeholder = "请选择",
    ariaLabel,
    disabled = false,
    size = "default",
    className = "",
    onValueChange
  }: Props = $props();

  let currentLabel = $derived(options.find((option) => option.value === value)?.label ?? placeholder);
</script>

<!-- 下拉选择：基于 shadcn Select，触发器铺满容器宽度 -->
<Select.Root
  type="single"
  {value}
  {disabled}
  onValueChange={(next) => {
    if (typeof next === "string" && next) onValueChange(next as T);
  }}
>
  <Select.Trigger aria-label={ariaLabel} {size} class={cn("w-full", className)}>
    <span class="truncate">{currentLabel}</span>
  </Select.Trigger>
  <Select.Content>
    {#each options as option (option.value)}
      <Select.Item value={option.value} disabled={option.disabled}>{option.label}</Select.Item>
    {/each}
  </Select.Content>
</Select.Root>
