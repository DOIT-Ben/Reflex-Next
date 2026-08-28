<script lang="ts">
  export let variant: "primary" | "secondary" | "quiet" | "danger" | "icon" = "secondary";
  export let type: "button" | "submit" | "reset" = "button";
  export let disabled = false;
  export let busy = false;
  export let ariaLabel: string | undefined = undefined;
  export let onclick: ((event: MouseEvent) => void) | undefined = undefined;
  let element: HTMLButtonElement;
  export function focus() { element?.focus(); }
</script>

<button bind:this={element} class:icon={variant === "icon"} class:busy class={`ui-button ${variant}`} {type} {disabled} aria-label={ariaLabel} {onclick}>
  <slot />
</button>
