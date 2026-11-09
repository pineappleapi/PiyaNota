import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/export_selection.dart';
import 'package:piyanota_application/models/voice_part.dart';

const Set<VoicePart> _all = {...VoicePart.values};

void main() {
  group('ExportSelection (PIYA-211)', () {
    test('preTicked keeps only available voices, and the click as given', () {
      final s = ExportSelection.preTicked(
        available: {VoicePart.soprano, VoicePart.alto},
        voices: {VoicePart.alto, VoicePart.tenor},
        withClick: true,
      );
      expect(s.voices, {VoicePart.alto});
      expect(s.withClick, isTrue);
      expect(s.allVoices, isFalse);
      expect(s.toggleVoice(VoicePart.soprano).allVoices, isTrue);
    });

    test('preTicked with only the click cannot download', () {
      final s = ExportSelection.preTicked(
        available: _all,
        voices: const {},
        withClick: true,
      );
      expect(s.canDownload, isFalse);
    });

    test('empty: nothing ticked', () {
      final s = ExportSelection.empty(_all);
      expect(s.voices, isEmpty);
      expect(s.withClick, isFalse);
      expect(s.allVoices, isFalse);
    });

    test('AC3: ticking All ticks every available voice', () {
      final s = ExportSelection.empty(_all).toggleAll();
      expect(s.voices, _all);
      expect(s.allVoices, isTrue);
    });

    test('AC4: unticking All clears every voice', () {
      final s = ExportSelection.empty(_all).toggleAll().toggleAll();
      expect(s.voices, isEmpty);
      expect(s.allVoices, isFalse);
    });

    test('AC5: unticking one voice unticks All', () {
      final s = ExportSelection.empty(_all)
          .toggleAll()
          .toggleVoice(VoicePart.alto);
      expect(s.allVoices, isFalse);
      expect(s.voices, {VoicePart.soprano, VoicePart.tenor, VoicePart.bass});
    });

    test('AC6: ticking all four by hand ticks All', () {
      var s = ExportSelection.empty(_all);
      for (final voice in VoicePart.values) {
        expect(s.allVoices, isFalse);
        s = s.toggleVoice(voice);
      }
      expect(s.allVoices, isTrue);
    });

    test('AC8: Download needs at least one voice; the click alone is not '
        'enough', () {
      final s = ExportSelection.empty(_all);
      expect(s.canDownload, isFalse);
      expect(s.toggleClick().canDownload, isFalse);
      expect(s.toggleVoice(VoicePart.bass).canDownload, isTrue);
    });

    test('the click toggles on and off', () {
      final s = ExportSelection.empty(_all).toggleClick();
      expect(s.withClick, isTrue);
      expect(s.toggleClick().withClick, isFalse);
    });

    group('Review Focus 4: an unavailable voice', () {
      final available = {VoicePart.soprano, VoicePart.alto, VoicePart.bass};

      test('cannot be ticked', () {
        final s = ExportSelection.empty(available).toggleVoice(VoicePart.tenor);
        expect(s.voices, isEmpty);
      });

      test('All means all available voices', () {
        final s = ExportSelection.empty(available).toggleAll();
        expect(s.voices, available);
        expect(s.allVoices, isTrue);
      });

      test('ticking the available ones by hand ticks All', () {
        var s = ExportSelection.empty(available);
        for (final voice in available) {
          s = s.toggleVoice(voice);
        }
        expect(s.allVoices, isTrue);
      });

      test('with no voice available, All stays unticked', () {
        final s = ExportSelection.empty(const {}).toggleAll();
        expect(s.allVoices, isFalse);
        expect(s.canDownload, isFalse);
      });
    });
  });

  group('exportFileName (AC14)', () {
    ExportSelection pick(Set<VoicePart> voices, {bool click = false}) {
      var s = ExportSelection.empty(_all);
      for (final voice in voices) {
        s = s.toggleVoice(voice);
      }
      return click ? s.toggleClick() : s;
    }

    test('voices in SATB order, joined by -, with _Click', () {
      expect(
        exportFileName(
          title: 'ClairDeLune',
          selection: pick({VoicePart.alto, VoicePart.soprano}, click: true),
        ),
        'ClairDeLune_Soprano-Alto_Click.mp3',
      );
    });

    test('every voice is AllVoices', () {
      expect(
        exportFileName(
          title: 'X',
          selection: ExportSelection.empty(_all).toggleAll(),
        ),
        'X_AllVoices.mp3',
      );
    });

    test('Review Focus 3: characters a file name cannot hold become _', () {
      expect(
        exportFileName(title: 'A/B', selection: pick({VoicePart.soprano})),
        'A_B_Soprano.mp3',
      );
      expect(
        exportFileName(
          title: r'a\b:c*d?e"f<g>h|i',
          selection: pick({VoicePart.tenor}),
        ),
        'a_b_c_d_e_f_g_h_i_Tenor.mp3',
      );
    });

    test('Review Focus 3: an empty or blank title is Score', () {
      expect(
        exportFileName(title: '', selection: pick({VoicePart.bass})),
        'Score_Bass.mp3',
      );
      expect(
        exportFileName(title: '   ', selection: pick({VoicePart.bass})),
        'Score_Bass.mp3',
      );
    });

    test('keeps spaces inside the title and trims the ends', () {
      expect(
        exportFileName(
          title: '  Bituin Walang Ningning ',
          selection: pick({VoicePart.alto}),
        ),
        'Bituin Walang Ningning_Alto.mp3',
      );
    });
  });

  group('uniqueFileName (AC15)', () {
    test('a free name is kept', () {
      expect(uniqueFileName('X.mp3', const {}), 'X.mp3');
    });

    test('a clash takes the first free (n)', () {
      expect(uniqueFileName('X.mp3', const {'X.mp3'}), 'X (1).mp3');
      expect(
        uniqueFileName('X.mp3', const {'X.mp3', 'X (1).mp3'}),
        'X (2).mp3',
      );
    });

    test(
      'clashes are found whatever the case, as shared storage ignores it',
      () {
        expect(uniqueFileName('X.mp3', const {'x.MP3'}), 'X (1).mp3');
      },
    );
  });
}
