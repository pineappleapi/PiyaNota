import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/screens/library/widgets/library_bottom_nav.dart';

void main() {
  testWidgets('capture glyph is a vertical sampled blue-to-teal gradient', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: CaptureGlyph())),
    );
    expect(find.byType(ShaderMask), findsOneWidget);
    expect(CaptureGlyph.gradient.begin, Alignment.topCenter);
    expect(CaptureGlyph.gradient.end, Alignment.bottomCenter);
    expect(CaptureGlyph.gradient.colors, const [
      Color(0xFF148FC7),
      Color(0xFF0AB7C1),
    ]);
  });
}
