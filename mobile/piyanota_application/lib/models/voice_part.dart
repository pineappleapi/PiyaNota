/// The four SATB voice parts, matching the constant voice names used
/// throughout the ML pipeline (Soprano/Alto/Tenor/Bass).
enum VoicePart {
  soprano('Soprano'),
  alto('Alto'),
  tenor('Tenor'),
  bass('Bass');

  const VoicePart(this.label);

  final String label;
}
