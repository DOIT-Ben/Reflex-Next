<script lang="ts">
  export let label = "";
  export let help = "";
</script>

<label class="ui-field">{#if label}<span>{label}</span>{/if}<slot />{#if help}<small>{help}</small>{/if}</label>
