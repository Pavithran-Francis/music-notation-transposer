I want you to build a complete, production-quality web application for automatically transposing sheet music from one instrument to another.

PROJECT NAME:
Sheet Music Transposer

CORE PURPOSE:
The user uploads a sheet-music PDF or PNG/image containing music written for one instrument. The application analyzes the sheet music, identifies the musical notation, determines the notes/rhythms/key signature/time signature/clef/etc., and produces a new sheet-music score transposed and formatted for a different instrument.

The goal is to eliminate the current manual workflow where I:
1. Write or obtain the original music in MuseScore.
2. Open MuseScore.
3. Add the target instrument.
4. Copy/paste the entire manuscript.
5. Manually fix or transpose anything that does not work.

The application should automate this entire workflow.

IMPORTANT:
This is NOT simply an image-to-text OCR application.
It must understand musical notation and preserve the musical structure of the original score.

==================================================
1. USER WORKFLOW
==================================================

The primary workflow should be:

STEP 1:
User opens the application.

STEP 2:
User uploads:
- PDF
- PNG
- JPG/JPEG
- optionally multiple image pages for multi-page scores

STEP 3:
The application displays a preview of the uploaded sheet music.

STEP 4:
The user selects the ORIGINAL INSTRUMENT.

Examples:
- Piano
- Flute
- Violin
- Viola
- Cello
- Double Bass
- Trumpet in Bb
- Clarinet in Bb
- Alto Saxophone in Eb
- Tenor Saxophone in Bb
- Baritone Saxophone in Eb
- French Horn in F
- Trombone
- Euphonium
- Tuba
- Oboe
- Bassoon
- Recorder
- Any other instrument that can be represented through standard transposition settings

Also allow:
"Custom instrument"

For custom instruments, allow the user to specify:
- transposition interval
- written range
- clef
- octave displacement
- whether the instrument sounds above/below written pitch

STEP 5:
The user selects the TARGET INSTRUMENT.

STEP 6:
The application analyzes the score.

STEP 7:
Show the detected musical information before generating the final result.

For example:

Detected:
Original instrument: Trumpet in Bb
Clef: Treble
Key signature: C major
Time signature: 4/4
Tempo: 120 BPM
Measures: 32
Detected notes: 247
Pages: 3

Provide an "Edit detected information" option so the user can correct mistakes.

STEP 8:
The application converts the music into an internal structured representation.

Do NOT immediately render the uploaded image as the output.

The system should first convert the notation into structured musical data.

Ideally use MusicXML as the canonical intermediate representation.

STEP 9:
Transpose the music from the source instrument to the target instrument.

STEP 10:
Render the resulting music as professional sheet music.

STEP 11:
Allow the user to preview the result.

STEP 12:
Allow export/download as:
- PDF
- MusicXML
- optionally MIDI
- optionally PNG/SVG

The final PDF should look like professionally engraved sheet music.

==================================================
2. MOST IMPORTANT TECHNICAL REQUIREMENT
==================================================

Use a structured musical representation internally.

The preferred pipeline is:

PDF/PNG
    ↓
Image preprocessing
    ↓
Music notation recognition / OMR
    ↓
Structured notation
    ↓
MusicXML
    ↓
Musical validation
    ↓
Instrument transposition
    ↓
MusicXML for target instrument
    ↓
Music engraving/rendering
    ↓
PDF/SVG/PNG/MIDI

Do NOT implement this as:

Image → OCR text → replace note names → PDF

That approach will fail for real sheet music.

The system must understand:
- pitch
- octave
- accidentals
- key signatures
- notes
- rests
- note durations
- tuplets
- ties
- slurs
- beams
- dotted notes
- grace notes
- dynamics
- articulations
- tempo markings
- repeats
- measure boundaries
- time signatures
- clefs
- multiple voices
- chords
- lyrics if present
- ornaments where possible
- rehearsal marks
- hairpins
- fermatas
- expression markings

==================================================
3. INPUT SUPPORT
==================================================

Support:

PDF:
- single-page PDF
- multi-page PDF
- scanned PDF
- digitally generated PDF

Images:
- PNG
- JPG/JPEG
- high-resolution scans
- photographs of sheet music if possible

For PDFs, determine whether the PDF already contains usable vector/text/music information.

If the PDF contains embedded MusicXML or accessible notation data, use it if possible rather than performing unnecessary OCR.

If the PDF is purely an image/scanned document, run OMR.

==================================================
4. MUSIC OMR
==================================================

The application needs Optical Music Recognition.

Do not build a primitive OCR system from scratch unless absolutely necessary.

Research and evaluate existing open-source music notation recognition technologies/libraries.

Potential technologies to investigate include:
- Audiveris
- OpenOMR
- OMR-related Python libraries
- music21
- MusicXML parsers
- Verovio
- MuseScore command-line tooling
- other actively maintained OMR systems

Choose the most reliable architecture.

If an external OMR engine is required, encapsulate it behind a clean service interface.

Example:

OMRService
    parseDocument()
    recognizePages()
    exportMusicXML()

The rest of the application should not depend directly on a particular OMR engine.

This will allow the OMR engine to be replaced later.

==================================================
5. MUSICXML
==================================================

MusicXML should be the canonical intermediate format wherever possible.

The system should be able to:

INPUT:
Image/PDF → MusicXML

TRANSPOSE:
Source MusicXML → Target MusicXML

OUTPUT:
Target MusicXML → PDF/SVG/PNG/MIDI

Use a reliable MusicXML parser and generator.

Do not manually construct MusicXML strings if a reliable library can be used.

==================================================
6. INSTRUMENT SYSTEM
==================================================

Create a proper instrument database.

Each instrument should contain information such as:

Instrument name
Instrument family
Written clef
Concert pitch relationship
Transposition interval
Typical range
Extended range
Octave displacement
Number of staves
Common notation conventions

Example:

Bb Trumpet:
Written C → sounds Bb
Therefore:
Written notation is a major second above concert pitch.

Eb Alto Saxophone:
Written C → sounds Eb
Therefore:
Written notation is a major sixth above concert pitch.

F Horn:
Written C → sounds F.

Clarinet in Bb:
Written C → sounds Bb.

The transposition engine must be based on pitch relationships, not hard-coded note replacements.

==================================================
7. TRANSPOSE ENGINE
==================================================

Implement a robust transposition engine.

The conceptual process should be:

Source written note
    ↓
Convert to sounding/concert pitch
    ↓
Convert concert pitch to target instrument written pitch
    ↓
Determine correct octave
    ↓
Determine appropriate accidental/key signature
    ↓
Output target notation

Example:

If the source instrument is Bb Trumpet and the target instrument is Alto Saxophone:

1. Interpret the trumpet's written note.
2. Convert it to concert pitch.
3. Determine the corresponding written pitch for Eb Alto Saxophone.
4. Preserve rhythmic value.
5. Preserve musical expression.
6. Select an appropriate enharmonic spelling.
7. Update the key signature when appropriate.
8. Ensure the resulting notation is readable.

Do not simply shift every note by a fixed number of semitones without considering notation spelling and instrument transposition.

==================================================
8. ENHARMONIC SPELLING
==================================================

This is extremely important.

The application should prefer musically correct spellings.

For example, do not randomly produce:

C# / Db
D# / Eb
G# / Ab

The system should consider:
- target key signature
- scale context
- melodic direction
- neighboring notes
- harmonic context where possible
- conventional notation practices

The output should look like something a professional musician would expect.

==================================================
9. KEY SIGNATURE
==================================================

When transposing:

- calculate the new key signature
- update the key signature
- preserve accidentals correctly
- handle explicit accidentals
- handle courtesy accidentals where possible

Example:

Original:
C major

Transposed for an instrument requiring a major second written transposition:

D major

The generated score should actually display the correct key signature rather than adding unnecessary accidentals to every note.

==================================================
10. CLEF HANDLING
==================================================

Support different clefs.

At minimum:
- Treble
- Bass
- Alto
- Tenor

The target instrument may require a different clef.

The application must be able to convert notation appropriately.

Example:

Cello → Violin

or

Bassoon → Trumpet

The musical pitch should remain correct while the written representation changes appropriately.

Do not merely change the clef symbol while leaving the notes incorrectly positioned.

==================================================
11. RANGE VALIDATION
==================================================

After transposition, check whether notes fall outside the practical range of the target instrument.

For example:

If a target instrument cannot normally play a particular note:

Display a warning:

"Warning:
The transposed score contains 3 notes outside the typical range of the selected instrument."

Highlight those notes in the preview.

Allow the user to choose:

[Keep original pitch]
[Move octave]
[Attempt automatic range correction]

Do NOT silently change musical pitches.

==================================================
12. OPTIONAL RANGE OPTIMIZATION
==================================================

Provide an optional setting:

"Optimize for target instrument"

When enabled, the application may intelligently move notes by octave when appropriate to make the music playable.

However:
- Never change the musical identity unnecessarily.
- Never silently change notes.
- Show every automatic adjustment.
- Provide an undo option.

==================================================
13. RHYTHM PRESERVATION
==================================================

Transposition must NEVER change rhythm.

Preserve:
- quarter notes
- eighth notes
- sixteenth notes
- thirty-second notes
- dotted rhythms
- ties
- tuplets
- rests
- syncopation
- beams

Only pitch-related information should change unless the user explicitly enables range optimization.

==================================================
14. MUSICAL STRUCTURE
==================================================

Preserve:
- measure numbers
- bar lines
- repeats
- first/second endings
- codas
- segnos
- rehearsal marks
- tempo markings
- dynamics
- articulations
- slurs
- ties
- lyrics
- chord symbols
- expressions

Where exact preservation is not possible, notify the user.

==================================================
15. MULTI-VOICE MUSIC
==================================================

Support multiple voices where possible.

Example:

A piano staff may contain:
Voice 1
Voice 2

Do not accidentally merge the voices.

Preserve independent rhythmic structures.

For multi-staff instruments, preserve staff relationships.

==================================================
16. CHORDS
==================================================

If the original contains chords:

C-E-G

the application must transpose the entire chord correctly.

Do not treat each note as an unrelated note.

Preserve chord structure.

Also support chord symbols where possible.

==================================================
17. USER INTERFACE
==================================================

Build a clean modern interface.

Suggested layout:

--------------------------------------------------
HEADER
Sheet Music Transposer
--------------------------------------------------

UPLOAD AREA

[ Drag & Drop PDF or Image ]

Supported:
PDF, PNG, JPG

--------------------------------------------------

SOURCE INSTRUMENT

[ Select Instrument ▼ ]

TARGET INSTRUMENT

[ Select Instrument ▼ ]

[ Advanced Settings ]

--------------------------------------------------

ANALYSIS

Original instrument:
Trumpet in Bb

Key:
C major

Time:
4/4

Clef:
Treble

Measures:
32

Confidence:
94%

[ Review Recognition ]

--------------------------------------------------

PREVIEW

Left:
Original score

Right:
Transposed score

Allow zooming.

Allow page navigation.

Highlight uncertain recognition.

--------------------------------------------------

OUTPUT

Format:
[ PDF ▼ ]

[ Generate Transposed Score ]

--------------------------------------------------

RESULT

[ Preview ]

[ Download PDF ]

[ Download MusicXML ]

[ Download MIDI ]

==================================================
18. RECOGNITION REVIEW
==================================================

Because OMR will not always be perfect, create a review interface.

If the system is uncertain about a note, mark it.

For example:

Measure 12
Beat 3

Detected:
F#

Confidence:
61%

User can click the note and change it.

The review editor should support:
- pitch
- accidental
- octave
- duration
- rest
- clef
- time signature
- key signature

Do not force users to manually correct the entire score.

Only uncertain regions should require attention.

==================================================
19. CONFIDENCE SYSTEM
==================================================

Every recognized element should have a confidence score where possible.

Example:

Note recognition:
98%

Rhythm:
95%

Clef:
99%

Time signature:
99%

Key signature:
94%

If confidence is low, ask for confirmation.

For example:

"Some notation could not be confidently recognized."

[Review 5 issues]

==================================================
20. OUTPUT QUALITY
==================================================

The final output must look like real engraved sheet music.

Avoid:
- ugly spacing
- overlapping notes
- incorrect beams
- broken ties
- incorrect accidentals
- inconsistent measure widths
- poor page breaks
- tiny notation
- huge empty spaces

Use a professional notation rendering engine.

Investigate:
- Verovio
- MuseScore CLI
- LilyPond
- other reliable notation rendering systems

Choose the best solution.

The application should ideally generate MusicXML and then use a professional engraving engine to produce PDF/SVG.

==================================================
21. MUSESCORE COMPATIBILITY
==================================================

The application should ideally support MusicXML generated by MuseScore.

This is important because my existing workflow uses MuseScore.

Allow:

Upload MusicXML

in addition to:

PDF
PNG
JPG

If the user uploads MusicXML, skip OMR entirely.

This should provide a much more accurate workflow.

Also allow exporting MusicXML so the result can be opened directly in MuseScore.

==================================================
22. MIDI SUPPORT
==================================================

Optionally generate MIDI.

The MIDI should represent the sounding/concert pitch correctly.

Make sure the MIDI output does not accidentally contain the written pitch instead of the intended sounding pitch.

==================================================
23. ARCHITECTURE
==================================================

Build the project with a modular architecture.

Suggested structure:

frontend/
    components/
    pages/
    services/
    editors/
    viewers/

backend/
    api/
    services/
        omr/
        musicxml/
        transposition/
        rendering/
        validation/
    models/
    workers/

core/
    instruments/
    music/
    transposition/
    validation/

The transposition logic should be independent of the UI.

==================================================
24. BACKEND
==================================================

Use a suitable backend framework.

Python is preferred if it provides easier integration with:
- music21
- MusicXML
- OMR
- music processing
- scientific libraries

A possible stack:

Frontend:
React + TypeScript

Backend:
Python + FastAPI

Music processing:
music21

Music notation:
MusicXML

Rendering:
Verovio and/or MuseScore CLI

Database:
PostgreSQL if persistent user projects are needed.

Object storage:
S3-compatible storage if deployed.

Background jobs:
Celery/RQ or an equivalent job system for expensive OMR tasks.

However, do not blindly follow this stack.

Evaluate the best technologies and use the simplest architecture that can reliably achieve the requirements.

==================================================
25. ASYNCHRONOUS PROCESSING
==================================================

OMR and rendering may take time.

Do not make the browser wait on a single HTTP request.

Use a job system.

Workflow:

Upload
 ↓
Create processing job
 ↓
OMR
 ↓
MusicXML generation
 ↓
Validation
 ↓
Transposition
 ↓
Rendering
 ↓
Complete

Frontend should display:

Uploading...
Analyzing page 1 of 4...
Recognizing notation...
Checking musical structure...
Transposing...
Rendering...
Complete.

==================================================
26. ERROR HANDLING
==================================================

Handle:

- corrupt PDFs
- unsupported image formats
- low-resolution images
- upside-down images
- rotated pages
- blank pages
- handwritten music
- heavily damaged scans
- unsupported notation
- incomplete scores
- OMR failures
- rendering failures
- invalid MusicXML
- notes outside target instrument range

Do not crash.

Provide useful messages.

Example:

"We couldn't reliably recognize page 2 because the image resolution is too low. Try uploading a scan at 300 DPI or higher."

==================================================
27. IMAGE PREPROCESSING
==================================================

For image-based sheet music, implement preprocessing where useful:

- deskew
- rotate
- crop
- grayscale
- noise reduction
- contrast adjustment
- resolution normalization
- staff-line detection
- perspective correction for photographs

Allow the user to manually rotate/crop if necessary.

==================================================
28. SECURITY
==================================================

Treat uploaded files as untrusted.

Implement:
- file size limits
- MIME validation
- safe temporary storage
- automatic cleanup
- isolated processing
- protection against malicious PDFs
- authentication if accounts are implemented

Never execute arbitrary content from uploaded files.

==================================================
29. PRIVACY
==================================================

Uploaded scores may be copyrighted or private.

Do not use uploaded files for training.

Delete temporary processing files after a reasonable period unless the user explicitly saves a project.

Clearly explain how files are handled.

==================================================
30. PROJECT STORAGE
==================================================

Allow users to save projects.

A project should contain:

Original file
Original MusicXML
Detected instrument
Target instrument
Recognition corrections
Transposition settings
Generated MusicXML
Generated PDF
Processing history

Allow:

New Project
Open Project
Rename
Delete
Duplicate

==================================================
31. UNDO / VERSIONING
==================================================

Keep the original score unchanged.

Every transformation should operate on a copy.

The user should be able to:

Original
 ↓
Recognition corrections
 ↓
Transposition
 ↓
Range adjustments

Allow undo where practical.

==================================================
32. API DESIGN
==================================================

Create clean APIs such as:

POST /projects
POST /projects/{id}/upload
POST /projects/{id}/analyze
GET /projects/{id}/analysis
PATCH /projects/{id}/corrections
POST /projects/{id}/transpose
GET /projects/{id}/preview
GET /projects/{id}/export/pdf
GET /projects/{id}/export/musicxml
GET /projects/{id}/export/midi

Use OpenAPI documentation.

==================================================
33. TESTING
==================================================

Testing is extremely important.

Create automated tests for:

Instrument transposition
Key signature conversion
Accidental handling
Enharmonic spelling
Octave handling
Clef conversion
Range checking
Rhythm preservation
Chord transposition
Multi-voice music
MusicXML parsing
MusicXML generation
PDF generation

Create test fixtures for common instruments.

Examples:

C instrument → Bb instrument
C instrument → Eb instrument
Bb → Eb
Eb → Bb
F → Bb
Bb → C
C → F

Also test:

C major → D major
F major → G major
Bb major → C major
Eb major → F major
G major → A major

==================================================
34. GOLDEN TEST FILES
==================================================

Create a test corpus containing simple known musical examples.

For every test:

INPUT:
Known MusicXML

SOURCE:
Instrument A

TARGET:
Instrument B

EXPECTED:
Known MusicXML

Compare the resulting musical pitches and rhythms programmatically.

Do not rely only on visual comparison.

==================================================
35. MUSICAL VALIDATION
==================================================

Before exporting, validate the resulting score.

Check:

- Every measure is rhythmically valid.
- Notes have valid durations.
- Voices are valid.
- Key signatures are valid.
- No invalid MusicXML structures exist.
- Target instrument is correctly represented.
- Transposition is mathematically correct.
- No notes were accidentally deleted.
- Number of measures is unchanged unless intentionally modified.
- Rhythmic structure is unchanged.

Display:

"Score validation passed."

or:

"3 issues require review."

==================================================
36. PERFORMANCE
==================================================

Optimize for:

- large multi-page scores
- 10+ page PDFs
- high-resolution scans
- multiple simultaneous users

Use background workers for expensive processing.

Do not load huge PDF/image files unnecessarily into browser memory.

Generate thumbnails for previews.

==================================================
37. RESPONSIVE DESIGN
==================================================

The application should work on:

Desktop
Tablet

Desktop should be the primary experience because sheet music requires screen space.

==================================================
38. ACCESSIBILITY
==================================================

Implement:

- keyboard navigation
- accessible buttons
- readable contrast
- descriptive labels
- screen-reader friendly controls where practical

==================================================
39. FUTURE FEATURES
==================================================

Design the architecture so these can be added later:

- handwritten music recognition
- audio → sheet music
- MIDI → sheet music
- MusicXML editing
- automatic orchestration
- instrument range optimization
- melody extraction
- part extraction
- transpose by arbitrary interval
- transpose entire score
- transpose selected measures
- batch processing
- cloud projects
- collaboration
- mobile application

Do not implement all of these now unless necessary.

Build the architecture so they can be added later.

==================================================
40. MVP PRIORITY
==================================================

Do NOT spend most of the development time building secondary features.

The MVP must first reliably accomplish:

1. Upload PDF/PNG/JPG.
2. Recognize standard printed sheet music.
3. Convert it to MusicXML.
4. Let the user select source instrument.
5. Let the user select target instrument.
6. Correctly transpose pitches.
7. Preserve rhythms and musical notation.
8. Render professional sheet music.
9. Preview the result.
10. Export PDF.
11. Export MusicXML.
12. Allow correction of OMR mistakes.

These are the critical features.

==================================================
41. IMPORTANT PRODUCT PRINCIPLE
==================================================

Accuracy is more important than flashy UI.

A beautiful application that produces incorrect notes is useless.

Prioritize in this order:

1. Musical correctness
2. OMR accuracy
3. Transposition correctness
4. MusicXML integrity
5. Engraving quality
6. Error correction workflow
7. Performance
8. UI polish

==================================================
42. DEVELOPMENT APPROACH
==================================================

Do not just give me a theoretical architecture.

Actually build the application.

Start by inspecting the existing project/repository.

If the repository is empty:
- initialize the project
- create the frontend
- create the backend
- configure development tooling
- create the required services
- create a working local development environment

Before writing large amounts of code, determine which OMR and notation libraries are realistically usable.

Prefer mature, proven open-source tools over implementing complex music-recognition algorithms from scratch.

==================================================
43. IMPLEMENTATION PHASES
==================================================

Build in these phases.

PHASE 1:
Project foundation

- frontend
- backend
- API
- file upload
- project model
- basic UI

PHASE 2:
MusicXML pipeline

- MusicXML upload
- MusicXML parsing
- instrument selection
- transposition engine
- MusicXML export

PHASE 3:
Rendering

- render MusicXML
- PDF output
- SVG preview
- score viewer

PHASE 4:
OMR

- PDF/image preprocessing
- OMR integration
- MusicXML extraction
- recognition confidence

PHASE 5:
Correction editor

- detect uncertain notation
- allow corrections
- regenerate MusicXML

PHASE 6:
Validation

- musical validation
- range checking
- warnings

PHASE 7:
Polish

- progress indicators
- error handling
- responsive UI
- performance optimization

==================================================
44. DEVELOPMENT RULE
==================================================

At every stage, keep the application runnable.

Do not build hundreds of files and only test at the end.

After each major feature:

1. Run the application.
2. Run automated tests.
3. Fix errors.
4. Verify the actual workflow.
5. Continue.

==================================================
45. DO NOT FAKE FUNCTIONALITY
==================================================

This is extremely important.

Do not create buttons that merely display:

"Coming soon"

Do not pretend that OCR has happened if it has not.

Do not hard-code example sheet music.

Do not hard-code a few transposition cases and call it a transposition engine.

Do not create a fake PDF generator that simply embeds the original image.

The output must be genuinely transposed musical notation.

If a capability cannot be implemented reliably with the current technology, clearly identify the limitation and implement the best practical alternative.

==================================================
46. FIRST DEMO TARGET
==================================================

The first fully working demo should support:

INPUT:
A clean printed single-page sheet music PDF/PNG.

SOURCE:
One of:
- C instrument
- Bb instrument
- Eb instrument
- F instrument

TARGET:
One of:
- C instrument
- Bb instrument
- Eb instrument
- F instrument

OUTPUT:
Correctly transposed MusicXML + professionally rendered PDF.

The user should be able to complete:

Upload → Select source → Select target → Analyze → Review → Transpose → Preview → Download

without manually opening MuseScore.

==================================================
47. FINAL ACCEPTANCE TEST
==================================================

Do not consider the project complete until this workflow works end-to-end:

1. Start application.
2. Upload a real printed sheet music PDF.
3. Application recognizes the score.
4. Application identifies musical structure.
5. User selects source instrument.
6. User selects target instrument.
7. Application calculates the correct transposition.
8. Application preserves rhythm.
9. Application preserves musical markings.
10. Application changes key signature correctly.
11. Application changes clef where required.
12. Application checks target range.
13. Application generates MusicXML.
14. Application renders the MusicXML.
15. User previews the transposed score.
16. User downloads PDF.
17. User downloads MusicXML.
18. Open the MusicXML in MuseScore and verify that it displays correctly.
19. Compare the original and transposed score to ensure the musical relationship is correct.

==================================================
48. DELIVERABLES
==================================================

At the end, provide:

1. Complete source code.
2. README.md.
3. Installation instructions.
4. Development instructions.
5. Production deployment instructions.
6. Environment variable documentation.
7. API documentation.
8. Database schema if applicable.
9. Testing instructions.
10. Explanation of the OMR engine used.
11. Explanation of the transposition algorithm.
12. Explanation of the rendering pipeline.
13. Known limitations.
14. Future improvements.

==================================================
49. IMPORTANT FINAL INSTRUCTION
==================================================

Think of this application as:

"An intelligent bridge between scanned sheet music and professional notation software."

The ideal user experience is:

I upload a sheet of music.
I tell the application what instrument it is currently written for.
I tell it what instrument I want.
The application understands the notation, performs the correct musical transposition, and gives me a clean professional score that I can open in MuseScore.

Build toward that exact experience.

Do not optimize for demonstrating code.
Optimize for producing a genuinely usable music-transposition application.

Before making architectural decisions, inspect the available libraries and tools and choose the most reliable practical implementation.

If an external dependency is required, document exactly how to install it.

If an external service/API is required, isolate it behind an abstraction so it can later be replaced.

When you finish each phase, verify it actually works before proceeding to the next phase.

Start by inspecting the repository and then implement Phase 1.