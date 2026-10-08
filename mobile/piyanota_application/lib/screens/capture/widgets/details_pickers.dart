import 'package:flutter/material.dart';

import '../../../models/score_details.dart';
import '../../../theme/app_theme.dart';
import '../capture_messages.dart';
import 'music_pictures.dart';

/// What a picker sheet returned. A sheet closed without choosing returns
/// null instead, so "Not sure" (a null [value]) is distinguishable.
class PickerChoice<T> {
  const PickerChoice(this.value);
  final T? value;
}

Future<PickerChoice<KeySignature>?> showKeySignaturePicker(
  BuildContext context,
  KeySignature? current,
) => _showSheet(
  context,
  title: CaptureMessages.keyQuestion,
  child: _KeyGrid(current: current),
);

Future<PickerChoice<TimeSignature>?> showTimeSignaturePicker(
  BuildContext context,
  TimeSignature? current,
) => _showSheet(
  context,
  title: CaptureMessages.beatsQuestion,
  child: _TimeGrid(current: current),
);

Future<PickerChoice<int>?> showTempoPicker(
  BuildContext context,
  int? current,
) => _showSheet(
  context,
  title: CaptureMessages.speedQuestion,
  child: _TempoPicker(initial: current ?? ScoreDetails.defaultTempo),
);

Future<PickerChoice<T>?> _showSheet<T>(
  BuildContext context, {
  required String title,
  required Widget child,
}) {
  return showModalBottomSheet<PickerChoice<T>>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    backgroundColor: Colors.white,
    builder: (context) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * 0.85,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Semantics(
                header: true,
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: AppTheme.captureInk,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              child,
            ],
          ),
        ),
      ),
    ),
  );
}

/// One selectable answer: a picture over a label, with a clear selected
/// state that doesn't rely on colour alone (border weight and a check).
class OptionCard extends StatelessWidget {
  const OptionCard({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
    required this.picture,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final Widget picture;

  @override
  Widget build(BuildContext context) {
    final border = selected
        ? AppTheme.primaryBlue
        : AppTheme.libraryCardOutline;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      excludeSemantics: true,
      onTap: onTap,
      child: Material(
        color: selected ? AppTheme.noticeBannerFill : Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: border, width: selected ? 2.5 : 1),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Stack(
                    alignment: Alignment.center,
                    children: [
                      picture,
                      if (selected)
                        const Positioned(
                          top: 0,
                          right: 0,
                          child: Icon(
                            Icons.check_circle_rounded,
                            size: 18,
                            color: AppTheme.primaryBlue,
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    label,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.captureInk,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Lays cards out in as many columns as fit [minCardWidth], so large text
/// drops to fewer columns instead of clipping.
class _OptionGrid extends StatelessWidget {
  const _OptionGrid({required this.children, this.minCardWidth = 132});

  final List<Widget> children;
  final double minCardWidth;

  static const double _gap = 8;

  @override
  Widget build(BuildContext context) {
    final scale = MediaQuery.textScalerOf(context).scale(1);
    return LayoutBuilder(
      builder: (context, constraints) {
        final min = minCardWidth * scale.clamp(1.0, 2.0);
        final columns = ((constraints.maxWidth + _gap) / (min + _gap))
            .floor()
            .clamp(1, 4);
        final width = (constraints.maxWidth - _gap * (columns - 1)) / columns;
        return Wrap(
          spacing: _gap,
          runSpacing: _gap,
          children: [
            for (final child in children) SizedBox(width: width, child: child),
          ],
        );
      },
    );
  }
}

class _NotSurePicture extends StatelessWidget {
  const _NotSurePicture();

  @override
  Widget build(BuildContext context) => const SizedBox(
    height: 44,
    child: Center(
      child: Icon(
        Icons.help_outline_rounded,
        size: 32,
        color: AppTheme.captureInk,
      ),
    ),
  );
}

class _KeyGrid extends StatelessWidget {
  const _KeyGrid({required this.current});

  final KeySignature? current;

  @override
  Widget build(BuildContext context) {
    void pick(KeySignature? value) =>
        Navigator.of(context).pop(PickerChoice<KeySignature>(value));
    return _OptionGrid(
      children: [
        OptionCard(
          label: CaptureMessages.notSure,
          selected: current == null,
          onTap: () => pick(null),
          picture: const _NotSurePicture(),
        ),
        for (final key in KeySignature.values)
          OptionCard(
            label: key.label,
            selected: current == key,
            onTap: () => pick(key),
            picture: KeySignatureStaff(keySignature: key),
          ),
      ],
    );
  }
}

class _TimeGrid extends StatelessWidget {
  const _TimeGrid({required this.current});

  final TimeSignature? current;

  @override
  Widget build(BuildContext context) {
    void pick(TimeSignature? value) =>
        Navigator.of(context).pop(PickerChoice<TimeSignature>(value));
    return _OptionGrid(
      minCardWidth: 96,
      children: [
        OptionCard(
          label: CaptureMessages.notSure,
          selected: current == null,
          onTap: () => pick(null),
          picture: const _NotSurePicture(),
        ),
        for (final time in TimeSignature.values)
          OptionCard(
            label: time.label,
            selected: current == time,
            onTap: () => pick(time),
            picture: SizedBox(
              height: 44,
              child: Center(child: StackedTimeSignature(timeSignature: time)),
            ),
          ),
      ],
    );
  }
}

class _TempoPicker extends StatefulWidget {
  const _TempoPicker({required this.initial});

  final int initial;

  @override
  State<_TempoPicker> createState() => _TempoPickerState();
}

class _TempoPickerState extends State<_TempoPicker> {
  late int _bpm = widget.initial;

  static const int _step = 1;

  void _set(int value) => setState(
    () => _bpm = value.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo),
  );

  @override
  Widget build(BuildContext context) {
    const ink = TextStyle(color: AppTheme.captureInk);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            IconButton.outlined(
              tooltip: CaptureMessages.slower,
              onPressed: _bpm > ScoreDetails.minTempo
                  ? () => _set(_bpm - _step)
                  : null,
              icon: const Icon(Icons.remove_rounded),
            ),
            Expanded(
              child: Semantics(
                liveRegion: true,
                child: Text(
                  CaptureMessages.tempoValue(_bpm),
                  textAlign: TextAlign.center,
                  style: ink.copyWith(
                    fontSize: 32,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
            IconButton.outlined(
              tooltip: CaptureMessages.faster,
              onPressed: _bpm < ScoreDetails.maxTempo
                  ? () => _set(_bpm + _step)
                  : null,
              icon: const Icon(Icons.add_rounded),
            ),
          ],
        ),
        Slider(
          value: _bpm.toDouble(),
          min: ScoreDetails.minTempo.toDouble(),
          max: ScoreDetails.maxTempo.toDouble(),
          divisions: ScoreDetails.maxTempo - ScoreDetails.minTempo,
          label: '$_bpm',
          semanticFormatterCallback: (v) =>
              CaptureMessages.tempoValue(v.round()),
          onChanged: (v) => _set(v.round()),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(child: Text(CaptureMessages.slow, style: ink)),
              Flexible(child: Text(CaptureMessages.medium, style: ink)),
              Flexible(child: Text(CaptureMessages.fast, style: ink)),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Text(CaptureMessages.speedHint, style: ink.copyWith(fontSize: 13)),
        const SizedBox(height: 16),
        Wrap(
          alignment: WrapAlignment.end,
          spacing: 8,
          runSpacing: 8,
          children: [
            TextButton(
              style: TextButton.styleFrom(foregroundColor: AppTheme.captureInk),
              onPressed: () =>
                  Navigator.of(context).pop(const PickerChoice<int>(null)),
              child: const Text(CaptureMessages.notSure),
            ),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AppTheme.libraryHeaderBottom,
                foregroundColor: Colors.white,
              ),
              onPressed: () =>
                  Navigator.of(context).pop(PickerChoice<int>(_bpm)),
              child: const Text(CaptureMessages.done),
            ),
          ],
        ),
      ],
    );
  }
}
