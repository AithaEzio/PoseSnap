export const settingsCategories = [
  { id: 'appearance', label: 'Appearance', description: 'Theme and motion preferences.' },
  { id: 'studio', label: 'Pose studio', description: 'Body-part selection and posing preferences.' },
  { id: 'extractions', label: 'Extractions', description: 'Pure SAM poses or Genesis Smart Fit.' },
  { id: 'daz', label: 'DAZ Studio', description: 'Application path and connected Genesis rigs.' },
  { id: 'engine', label: 'Engine', description: 'Engine health, components, downloads and recovery.' },
  { id: 'about', label: 'About', description: 'App identity, privacy and mannequin credits.' }
] as const;
export type SettingsCategory = typeof settingsCategories[number]['id'];
