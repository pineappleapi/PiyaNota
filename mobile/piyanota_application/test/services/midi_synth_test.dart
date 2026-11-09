import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/midi_synth.dart';

void main() {
  test('scaleWav scales samples, clamps, keeps header', () async {
    final Directory d = Directory.systemTemp.createTempSync('synth');
    addTearDown(() => d.deleteSync(recursive: true));
    final File f = File('${d.path}/t.wav');
    final ByteData bd = ByteData(44 + 8);
    for (int i = 0; i < 44; i++) {
      bd.setUint8(i, i);
    }
    final List<int> samples = <int>[1000, -1000, 30000, -30000];
    for (int i = 0; i < 4; i++) {
      bd.setInt16(44 + 2 * i, samples[i], Endian.little);
    }
    f.writeAsBytesSync(bd.buffer.asUint8List());

    await scaleWav(f.path, 1.5);

    final Uint8List out = f.readAsBytesSync();
    final ByteData o = ByteData.sublistView(out);
    expect(out.sublist(0, 44), List<int>.generate(44, (int i) => i));
    expect(o.getInt16(44, Endian.little), 1500);
    expect(o.getInt16(46, Endian.little), -1500);
    expect(o.getInt16(48, Endian.little), 32767);
    expect(o.getInt16(50, Endian.little), -32768);
  });
}
