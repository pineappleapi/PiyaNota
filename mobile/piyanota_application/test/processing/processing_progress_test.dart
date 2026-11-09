import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/state/processing_providers.dart';

ProcessingStatus _status(ProcessingStage stage, {int? percent}) =>
    ProcessingStatus(stage: stage, percentComplete: percent);

/// Folds a sequence of polls the way the tracker does, starting from 0%.
List<int> _shown(List<ProcessingStatus> polls) {
  var shown = 0;
  return [
    for (final poll in polls)
      shown = ProcessingProgress.next(previous: shown, status: poll),
  ];
}

void main() {
  group('ProcessingProgress.next (J5)', () {
    test('the shown percentage never goes backwards', () {
      final shown = _shown([
        _status(ProcessingStage.transcribing, percent: 50),
        _status(ProcessingStage.transcribing, percent: 42),
        _status(ProcessingStage.transcribing, percent: 60),
        _status(ProcessingStage.transcribing, percent: 55),
        _status(ProcessingStage.transcribing, percent: 60),
      ]);

      expect(shown, [50, 50, 60, 60, 60]);
    });

    test('a running job shows at most 99 even if the server says 100', () {
      final shown = _shown([
        _status(ProcessingStage.synthesizing, percent: 98),
        _status(ProcessingStage.synthesizing, percent: 100),
        _status(ProcessingStage.synthesizing, percent: 100),
      ]);

      expect(shown, [98, 99, 99]);
      expect(ProcessingProgress.maxBeforeComplete, 99);
    });

    test('complete reads 100 regardless of the reported value', () {
      expect(
        ProcessingProgress.next(
          previous: 99,
          status: _status(ProcessingStage.complete, percent: null),
        ),
        100,
      );
    });

    test('a failed job keeps the last shown value when it reports lower', () {
      final shown = _shown([
        _status(ProcessingStage.transcribing, percent: 70),
        _status(ProcessingStage.failed, percent: 30),
      ]);

      expect(shown, [70, 70]);
    });

    test('null percentComplete falls back to the stage band start', () {
      expect(
        ProcessingProgress.next(
          previous: 0,
          status: _status(ProcessingStage.preprocessing),
        ),
        5,
      );
      expect(
        ProcessingProgress.next(
          previous: 0,
          status: _status(ProcessingStage.detectingStaff),
        ),
        25,
      );
      expect(
        ProcessingProgress.next(
          previous: 0,
          status: _status(ProcessingStage.transcribing),
        ),
        40,
      );
      expect(
        ProcessingProgress.next(
          previous: 0,
          status: _status(ProcessingStage.reconstructing),
        ),
        85,
      );
      expect(
        ProcessingProgress.next(
          previous: 0,
          status: _status(ProcessingStage.synthesizing),
        ),
        92,
      );
    });

    test('null on queued keeps the previous value (no band)', () {
      expect(
        ProcessingProgress.next(
          previous: 3,
          status: _status(ProcessingStage.queued),
        ),
        3,
      );
    });
  });
}
