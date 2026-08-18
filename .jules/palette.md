## 2024-05-18 - [ARIA Labels for FontAwesome Icons]
**Learning:** In projects that use FontAwesome heavily without built-in accessibility safeguards, raw `<i class="fa-solid ..."></i>` tags used purely for visual flair alongside text can result in confusing screen reader output or redundant elements.
**Action:** When adding or verifying icons, always ensure they have `aria-hidden="true"` if they are decorative, and if they stand alone as actionable buttons, ensure the parent `<button>` has a clear, descriptive `aria-label`.
