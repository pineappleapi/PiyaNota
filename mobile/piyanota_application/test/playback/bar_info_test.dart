import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/measure_table.dart';

void main() {
  const base = {'bar': 1, 'startTick': 0, 'durTicks': 1920};

  test('reads the bar position fields', () {
    final bar = BarInfo.tryParse({
      ...base,
      'startMs': 0,
      'x': 187.5,
      'pageIndex': 1,
      'systemIndex': 2,
      'systemTopY': 240,
      'systemBottomY': 360.5,
    })!;
    expect(bar.x, 187.5);
    expect((bar.pageIndex, bar.systemIndex), (1, 2));
    expect((bar.systemTopY, bar.systemBottomY), (240, 360.5));
    expect(bar.hasPosition, isTrue);
  });

  test('an old row has no position and still parses', () {
    final bar = BarInfo.tryParse({...base, 'startMs': 0})!;
    expect(bar.x, isNull);
    expect(bar.hasPosition, isFalse);
  });

  test('bad values give null, never discard the bar', () {
    final bar = BarInfo.tryParse({
      ...base,
      'startMs': 0,
      'x': -3,
      'pageIndex': 'a',
      'systemIndex': -1,
      'systemTopY': 300,
      'systemBottomY': 200,
    })!;
    expect(bar.x, isNull);
    expect(bar.pageIndex, isNull);
    expect(bar.systemIndex, isNull);
    expect(bar.systemTopY, isNull);
    expect(bar.systemBottomY, isNull);
    expect(bar.hasPosition, isFalse);
  });
}
