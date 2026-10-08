import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../models/score_details.dart';
import '../../routes/app_routes.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import 'capture_messages.dart';
import 'widgets/details_pickers.dart';
import 'widgets/music_pictures.dart';

/// Step 1 of Add Score (PIYA-206): the song's title and optional details.
/// This screen stays under Capture on the stack, so its answers are still
/// here when the user comes back from step 2.
///
/// With [initial] set it edits answers already given: Capture opens it so
/// a field the server rejected can be fixed without losing the pages, and
/// "Save details" pops with the new [ScoreDetails] (Cancel pops null).
class ScoreDetailsScreen extends StatefulWidget {
  const ScoreDetailsScreen({super.key, this.initial});

  final ScoreDetails? initial;

  @override
  State<ScoreDetailsScreen> createState() => _ScoreDetailsScreenState();
}

class _ScoreDetailsScreenState extends State<ScoreDetailsScreen> {
  final _title = TextEditingController();
  final _composer = TextEditingController();
  KeySignature? _key;
  TimeSignature? _time;
  int? _tempo;

  /// Above this text scale the three tiles and the two buttons stack, so
  /// nothing clips on a 320 dp phone (NFR-10).
  static const double _stackTextScale = 1.3;
  static const double _gutter = 16;

  bool get _editing => widget.initial != null;

  @override
  void initState() {
    super.initState();
    if (widget.initial case final initial?) _apply(initial);
    _hadTitle = _title.text.trim().isNotEmpty;
    _title.addListener(_onTitleChanged);
  }

  void _apply(ScoreDetails details) {
    _title.text = details.title;
    _composer.text = details.composer;
    _key = details.keySignature;
    _time = details.timeSignature;
    _tempo = details.tempoBpm;
  }

  @override
  void dispose() {
    _title
      ..removeListener(_onTitleChanged)
      ..dispose();
    _composer.dispose();
    super.dispose();
  }

  bool _hadTitle = false;

  void _onTitleChanged() {
    final hasTitle = _title.text.trim().isNotEmpty;
    if (hasTitle != _hadTitle) setState(() => _hadTitle = hasTitle);
  }

  ScoreDetails get _details => ScoreDetails(
    title: _title.text.trim(),
    composer: _composer.text.trim(),
    keySignature: _key,
    timeSignature: _time,
    tempoBpm: _tempo,
  );

  Future<void> _next() async {
    if (!_hadTitle) return;
    FocusScope.of(context).unfocus();
    if (_editing) {
      Navigator.of(context).pop(_details);
      return;
    }
    // Capture hands back the details if they were edited there, so this
    // form shows what will actually be sent.
    final edited = await Navigator.of(context).pushNamed<Object?>(
      AppRoutes.capturePages,
      arguments: CapturePagesArguments(details: _details),
    );
    if (edited is ScoreDetails && mounted) setState(() => _apply(edited));
  }

  Future<void> _pickKey() async {
    final choice = await showKeySignaturePicker(context, _key);
    if (choice != null && mounted) setState(() => _key = choice.value);
  }

  Future<void> _pickTime() async {
    final choice = await showTimeSignaturePicker(context, _time);
    if (choice != null && mounted) setState(() => _time = choice.value);
  }

  Future<void> _pickTempo() async {
    final choice = await showTempoPicker(context, _tempo);
    if (choice != null && mounted) setState(() => _tempo = choice.value);
  }

  @override
  Widget build(BuildContext context) {
    final stacked = MediaQuery.textScalerOf(context).scale(1) > _stackTextScale;
    final form = <Widget>[
      _LabelledField(
        label: CaptureMessages.titleLabel,
        child: _DetailsTextField(
          controller: _title,
          hint: CaptureMessages.titleHint,
          icon: Icons.music_note_rounded,
          autofocus: !_editing,
          textInputAction: TextInputAction.next,
        ),
      ),
      const SizedBox(height: 16),
      _LabelledField(
        label: CaptureMessages.composerLabel,
        child: _DetailsTextField(
          controller: _composer,
          hint: CaptureMessages.composerHint,
          icon: Icons.person_outline_rounded,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _next(),
        ),
      ),
      const SizedBox(height: 28),
      Semantics(
        header: true,
        child: Text(
          CaptureMessages.musicSection,
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w700,
            color: AppTheme.captureInk,
          ),
        ),
      ),
      const SizedBox(height: 4),
      Text(
        CaptureMessages.musicSectionHint,
        style: Theme.of(context).textTheme.bodySmall
            ?.copyWith(color: AppTheme.libraryScoreSubtitle),
      ),
      const SizedBox(height: 12),
      _MusicTiles(
        stacked: stacked,
        tiles: [
          _MusicTile(
            title: CaptureMessages.keyTile,
            value: _key?.label ?? CaptureMessages.notSure,
            picture: KeySignatureStaff(keySignature: _key),
            onTap: _pickKey,
            horizontal: stacked,
          ),
          _MusicTile(
            title: CaptureMessages.beatsTile,
            value: _time?.label ?? CaptureMessages.notSure,
            picture: StackedTimeSignature(timeSignature: _time),
            onTap: _pickTime,
            horizontal: stacked,
          ),
          _MusicTile(
            title: CaptureMessages.speedTile,
            value: _tempo == null
                ? CaptureMessages.notSure
                : CaptureMessages.tempoValue(_tempo!),
            picture: Text(
              CaptureMessages.tempoValue(_tempo ?? ScoreDetails.defaultTempo),
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: AppTheme.captureInk,
              ),
            ),
            onTap: _pickTempo,
            horizontal: stacked,
          ),
        ],
      ),
    ];
    final buttons = SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(_gutter, 8, _gutter, 12),
        child: _Buttons(
          stacked: stacked,
          nextLabel: _editing
              ? CaptureMessages.saveDetails
              : CaptureMessages.nextAddPages,
          onCancel: () => Navigator.of(context).maybePop(),
          onNext: _hadTitle ? _next : null,
        ),
      ),
    );
    const formPadding = EdgeInsets.fromLTRB(_gutter, 20, _gutter, 24);
    if (stacked) {
      // With large text the header and stacked buttons alone can fill a
      // small phone, leaving the pinned form a sliver (NFR-10). Scroll
      // everything together instead.
      return Scaffold(
        backgroundColor: Colors.white,
        body: ListView(
          padding: EdgeInsets.zero,
          children: [
            _Header(editing: _editing),
            Padding(
              padding: formPadding,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: form,
              ),
            ),
            buttons,
          ],
        ),
      );
    }
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          _Header(editing: _editing),
          Expanded(
            child: ListView(padding: formPadding, children: form),
          ),
          buttons,
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.editing});

  final bool editing;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return DecoratedBox(
      decoration: const BoxDecoration(gradient: AppTheme.libraryHeaderGradient),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: Text(
                  editing
                      ? CaptureMessages.editDetailsTitle
                      : CaptureMessages.detailsTitle,
                  style: textTheme.headlineSmall?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              if (!editing) ...[
                const SizedBox(height: 4),
                Text(
                  CaptureMessages.detailsStep,
                  style: textTheme.bodyMedium?.copyWith(color: Colors.white),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _LabelledField extends StatelessWidget {
  const _LabelledField({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
            color: AppTheme.captureInk,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        child,
      ],
    );
  }
}

/// Caps input at [ScoreDetails.maxTextLength] Unicode code points — the
/// unit PIYA-101 AC8 counts — instead of TextField's grapheme `maxLength`,
/// which would let an emoji-heavy title through at more than 120 code
/// points. Cuts on rune boundaries so a pasted surrogate pair never splits.
class CodePointLimitFormatter extends TextInputFormatter {
  const CodePointLimitFormatter(this.limit);

  final int limit;

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    if (newValue.text.runes.length <= limit) return newValue;
    if (oldValue.text.runes.length >= limit &&
        newValue.text.length > oldValue.text.length) {
      return oldValue;
    }
    final clipped = String.fromCharCodes(newValue.text.runes.take(limit));
    return TextEditingValue(
      text: clipped,
      selection: TextSelection.collapsed(offset: clipped.length),
    );
  }
}

class _DetailsTextField extends StatelessWidget {
  const _DetailsTextField({
    required this.controller,
    required this.hint,
    required this.icon,
    this.autofocus = false,
    this.textInputAction,
    this.onSubmitted,
  });

  final TextEditingController controller;
  final String hint;
  final IconData icon;
  final bool autofocus;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onSubmitted;

  static OutlineInputBorder _pill([BorderSide side = BorderSide.none]) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(999),
        borderSide: side,
      );

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      autofocus: autofocus,
      textInputAction: textInputAction,
      textCapitalization: TextCapitalization.words,
      onSubmitted: onSubmitted,
      inputFormatters: const [
        CodePointLimitFormatter(ScoreDetails.maxTextLength),
      ],
      style: const TextStyle(color: AppTheme.captureInk),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: AppTheme.authSubtitle),
        prefixIcon: Icon(icon, color: AppTheme.authFieldIcon),
        filled: true,
        fillColor: AppTheme.authFieldFill,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 20,
          vertical: 16,
        ),
        border: _pill(),
        enabledBorder: _pill(),
        focusedBorder: _pill(
          const BorderSide(color: AppTheme.primaryBlue, width: 1.5),
        ),
      ),
    );
  }
}

class _MusicTiles extends StatelessWidget {
  const _MusicTiles({required this.stacked, required this.tiles});

  final bool stacked;
  final List<Widget> tiles;

  static const double _gap = 8;

  @override
  Widget build(BuildContext context) {
    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < tiles.length; i++) ...[
            if (i > 0) const SizedBox(height: _gap),
            tiles[i],
          ],
        ],
      );
    }
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < tiles.length; i++) ...[
            if (i > 0) const SizedBox(width: _gap),
            Expanded(child: tiles[i]),
          ],
        ],
      ),
    );
  }
}

class _MusicTile extends StatelessWidget {
  const _MusicTile({
    required this.title,
    required this.value,
    required this.picture,
    required this.onTap,
    required this.horizontal,
  });

  final String title;
  final String value;
  final Widget picture;
  final VoidCallback onTap;
  final bool horizontal;

  static const double _pictureHeight = 48;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final labels = Column(
      crossAxisAlignment: horizontal
          ? CrossAxisAlignment.start
          : CrossAxisAlignment.center,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          title,
          style: textTheme.labelLarge?.copyWith(
            fontWeight: FontWeight.w700,
            color: AppTheme.captureInk,
          ),
        ),
        Text(
          value,
          textAlign: horizontal ? TextAlign.start : TextAlign.center,
          style: textTheme.bodySmall?.copyWith(
            color: AppTheme.libraryScoreSubtitle,
          ),
        ),
      ],
    );
    final art = SizedBox(
      height: _pictureHeight,
      child: Center(child: FittedBox(child: picture)),
    );
    return Semantics(
      button: true,
      label: '$title: $value',
      excludeSemantics: true,
      onTap: onTap,
      child: Material(
        color: AppTheme.libraryAddTileFill,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: AppTheme.libraryCardOutline),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: horizontal
                ? Row(
                    children: [
                      SizedBox(width: 88, child: art),
                      const SizedBox(width: 12),
                      Expanded(child: labels),
                      const Icon(
                        Icons.chevron_right_rounded,
                        color: AppTheme.captureInk,
                      ),
                    ],
                  )
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [art, const SizedBox(height: 6), labels],
                  ),
          ),
        ),
      ),
    );
  }
}

class _Buttons extends StatelessWidget {
  const _Buttons({
    required this.stacked,
    required this.nextLabel,
    required this.onCancel,
    required this.onNext,
  });

  final bool stacked;
  final String nextLabel;
  final VoidCallback onCancel;
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) {
    final cancel = OutlinedButton(
      onPressed: onCancel,
      style: OutlinedButton.styleFrom(
        foregroundColor: AppTheme.captureInk,
        side: const BorderSide(color: AppTheme.libraryCardOutline),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
        shape: const StadiumBorder(),
      ),
      child: const Text(CaptureMessages.cancel),
    );
    final next = PrimaryPillButton(
      label: nextLabel,
      onPressed: onNext,
      backgroundColor: AppTheme.libraryHeaderBottom,
    );
    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [next, const SizedBox(height: 8), cancel],
      );
    }
    return Row(
      children: [
        cancel,
        const SizedBox(width: 12),
        Expanded(child: next),
      ],
    );
  }
}
