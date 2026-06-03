## 2025-06-03 - FontAwesome Icon Accessibility
**Learning:** FontAwesome icons (`<i class="fa-solid ...">`) can cause confusing and redundant announcements for screen reader users when used alongside visible text or ARIA labels.
**Action:** Always include the `aria-hidden="true"` attribute on FontAwesome icons to hide them from assistive technologies, ensuring a cleaner auditory experience.
