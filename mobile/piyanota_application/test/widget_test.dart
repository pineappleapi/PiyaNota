import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/app.dart';

void main() {
  testWidgets('App shell builds without error', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: PiyaNotaApp()));

    expect(find.text('PiyaNota'), findsOneWidget);
  });
}
