## 2024-06-11 - [Password Toggle Buttons]
**Learning:** Interactive reveal buttons like password toggles should not have `tabindex="-1"` as it prevents keyboard navigation. Additionally, internal decorative icons inside such buttons should have `aria-hidden="true"` to prevent screen readers from redundantly announcing the icon along with the button's `aria-label`.
**Action:** Always ensure interactive elements are keyboard accessible and use `aria-hidden="true"` for decorative icons within buttons that already have `aria-label`s.
