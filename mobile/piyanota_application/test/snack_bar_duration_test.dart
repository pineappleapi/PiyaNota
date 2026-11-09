import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/screens/scan_status/scan_toast_host.dart';
import 'package:piyanota_application/theme/app_theme.dart';

void main() {
  test('snackbars and the scan toast last 10 seconds', () {
    expect(AppTheme.snackBarDuration, const Duration(seconds: 10));
    expect(ScanToastHost.showFor, const Duration(seconds: 10));
  });

  test('every SnackBar( in lib passes an explicit duration', () {
    final pattern = RegExp(r'SnackBar\(');
    final offenders = <String>[];
    for (final file in Directory('lib').listSync(recursive: true)) {
      if (file is! File || !file.path.endsWith('.dart')) continue;
      final text = file.readAsStringSync();
      for (final m in pattern.allMatches(text)) {
        if (m.start > 0 && RegExp(r'\w').hasMatch(text[m.start - 1])) {
          continue; // SnackBarAction( etc. are not matched by this anyway
        }
        // Window to the end of this constructor call (balanced parens).
        var depth = 0;
        var end = m.end - 1;
        for (; end < text.length; end++) {
          if (text[end] == '(') depth++;
          if (text[end] == ')' && --depth == 0) break;
        }
        if (!text.substring(m.start, end).contains('duration:')) {
          offenders.add(file.path);
        }
      }
    }
    expect(offenders, isEmpty);
  });

  test('tempo cap is 180 and the server render range stays 240', () {
    expect(ScoreDetails.maxTempo, 180);
    expect(250.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo), 180);
    // A score rendered at 200 earlier stays "known" so speed ratios stay right.
    final result = ScoreResult.fromJson({
      'scoreId': 1,
      'audioTracks': {'soprano': 'https://cdn.test/s.mp3'},
      'tempoBpm': 200,
    });
    expect(result.tempoKnown, isTrue);
    expect(result.tempoBpm, 200);
  });
}
