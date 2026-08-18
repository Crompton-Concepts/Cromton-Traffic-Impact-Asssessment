## 2026-06-28 - Added aria-hidden to decorative FontAwesome icons
**Learning:** Decorative icons (like FontAwesome `<i class="fa-solid...">`) without `aria-hidden="true"` cause screen readers to announce confusing CSS class names or blank Unicode characters, degrading the accessibility experience.
**Action:** Always verify that decorative icons have `aria-hidden="true"` to hide them from the accessibility tree, especially when they accompany visible text or are inside interactive elements with existing ARIA labels.
