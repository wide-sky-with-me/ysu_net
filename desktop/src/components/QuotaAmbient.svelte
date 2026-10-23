<script lang="ts">
  import { ambientMotion } from '../lib/motion';
</script>

<!-- Decorative motion only: this is not a quota percentage or a live-traffic chart. -->
<!-- Keep this decoration text-free so copying the quota never adds whitespace. -->
<div class="quota-ambient" use:ambientMotion aria-hidden="true"><svg class="quota-wave-layer" viewBox="0 0 600 90" preserveAspectRatio="none" focusable="false"><path fill="currentColor" d="M0 30C50 10 100 10 150 30S250 50 300 30S400 10 450 30S550 50 600 30V90H0Z" /></svg><svg class="quota-wave-layer" viewBox="0 0 600 90" preserveAspectRatio="none" focusable="false"><path fill="currentColor" d="M0 30C50 10 100 10 150 30S250 50 300 30S400 10 450 30S550 50 600 30V90H0Z" /></svg></div>
