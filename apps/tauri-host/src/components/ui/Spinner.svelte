<script lang="ts">
  export let size = 13;
  export let thickness = 2;
  export let label = "";
</script>

<span
  class="ui-spinner"
  role={label ? "status" : undefined}
  aria-label={label || undefined}
  aria-hidden={label ? undefined : "true"}
  style={`width: ${size}px; height: ${size}px; flex-basis: ${size}px; border-width: ${thickness}px`}
></span>

<style>
  .ui-spinner {
    flex: 0 0 auto;
    border-style: solid;
    border-color: color-mix(in srgb, var(--accent, #5065c7) 20%, transparent);
    border-top-color: var(--accent, #5065c7);
    border-radius: 50%;
    animation: ui-spinner-spin 850ms linear infinite;
  }

  @keyframes ui-spinner-spin {
    to {
      transform: rotate(360deg);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .ui-spinner {
      animation-duration: 1.8s;
    }
  }
</style>
