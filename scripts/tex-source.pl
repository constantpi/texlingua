#!/usr/bin/env perl
use strict;
use warnings;
use utf8;
use Cwd qw(abs_path);
use File::Find qw(find);
use File::Spec;
use Encode qw(decode FB_CROAK);

binmode STDOUT, ':encoding(UTF-8)';
binmode STDERR, ':encoding(UTF-8)';

sub read_lines {
    my ($file) = @_;
    open my $fh, '<:raw', $file or die "$file: $!\n";
    my @lines = <$fh>;
    close $fh or die "$file: $!\n";
    return @lines;
}

sub tex_files {
    my ($root) = @_;
    my @files;
    find({ no_chdir => 1, wanted => sub {
        die "$File::Find::name: symbolic links are not supported; use regular files.\n" if -l $_;
        push @files, $File::Find::name if -f $_ && /\.tex\z/;
    } }, $root);
    return sort @files;
}

sub preprocess {
    my ($file, $mode, $entry) = @_;
    $mode //= 'ja';
    my @lines = read_lines($file);
    my @result;
    my @alignments;
    for (my $i = 0; $i < @lines; ++$i) {
        if ($lines[$i] =~ /^([\t ]*)%j[\t ]+(.*)/s) {
            my ($indent, $body) = ($1, $2);
            if ($i + 1 == @lines || $lines[$i + 1] =~ /^[\t ]*(?:%|\r?\n|\z)/) {
                die "$file:" . ($i + 1) . ": %j must be followed by one nonempty, non-comment English line.\n";
            }
            if ($mode eq 'both') {
                my $english = $lines[$i + 1];
                # Only the emitted English line changes the ongoing state.
                # Check the Japanese line separately for inline environment starts.
                my @japanese_state = @alignments;
                my $in_alignment = track_alignments($body, \@japanese_state);
                $in_alignment = track_alignments($english, \@alignments) || $in_alignment;
                # Deliberately lexical: any leading command selects English only.
                if (!$in_alignment && $body !~ /^[\t ]*\\/ && $english !~ /^[\t ]*\\/) {
                    my $newline = $body =~ /\r\n\z/ ? "\r\n" : "\n";
                    push @result, $indent . '{\small\color[gray]{0.45}%' . $newline,
                        $indent . $body, $indent . '\unskip}\space' . $newline;
                }
                push @result, $english;
            } else {
                push @result, $indent . $body;
            }
            ++$i;
        } else {
            track_alignments($lines[$i], \@alignments) if $mode eq 'both';
            push @result, $lines[$i];
        }
    }
    if ($entry) {
        # Register before reading the document, but load color after its own
        # preamble. Existing color/xcolor options must take precedence.
        my $support = <<'TEX';
% texlingua: both-mode support (temporary copy only).
\ifdefined\AddToHook
  \AddToHook{begindocument/before}{%
    \ifdefined\color\else
      \ifdefined\kanjiskip
        \RequirePackage[dvipdfmx]{color}%
      \else
        \RequirePackage{color}%
      \fi
    \fi
  }
\else
  \PackageError{texlingua}{both mode requires LaTeX 2020-10-01 or newer}{Update your LaTeX format.}
\fi
TEX
        $support =~ s/\n/\r\n/g if @lines && $lines[0] =~ /\r\n\z/;
        # Keep a UTF-8 BOM at the start rather than moving it into the preamble.
        my $bom = @result && $result[0] =~ s/\A\xEF\xBB\xBF// ? "\xEF\xBB\xBF" : '';
        unshift @result, $bom . $support;
    }
    open my $fh, '>:raw', $file or die "$file: $!\n";
    print {$fh} @result or die "$file: $!\n";
    close $fh or die "$file: $!\n";
}

sub code_only {
    my ($line) = @_;
    my $slashes = 0;
    for (my $i = 0; $i < length $line; ++$i) {
        my $char = substr($line, $i, 1);
        return substr($line, 0, $i) if $char eq '%' && $slashes % 2 == 0;
        $slashes = $char eq '\\' ? $slashes + 1 : 0;
    }
    return $line;
}

sub track_alignments {
    my ($line, $stack) = @_;
    my $inside = @$stack ? 1 : 0;
    my $code = code_only($line);
    # Match literal commands with an odd number of leading backslashes.
    # The stack is local to each file; macro expansion and \input are not parsed.
    while ($code =~ /(?<!\\)(?:\\\\)*\\(begin|end)[\t ]*\{[\t ]*(tabular|aligned)[\t ]*\}/g) {
        my ($command, $environment) = ($1, $2);
        if ($command eq 'begin') {
            push @$stack, $environment;
            $inside = 1;
        } elsif (@$stack && $stack->[-1] eq $environment) {
            pop @$stack;
        }
    }
    return $inside;
}

sub scan {
    my ($root, $recorder, $entry) = @_;
    $root = abs_path($root);
    my %files;
    if (-f $recorder) {
        my $pwd = $root;
        for my $line (read_lines($recorder)) {
            $line =~ s/\r?\n\z//;
            if ($line =~ /^PWD (.*)/) { $pwd = $1; next; }
            next unless $line =~ /^INPUT (.*\.tex)\z/;
            my $path = abs_path(File::Spec->rel2abs($1, $pwd));
            next unless defined $path && index($path, "$root/") == 0 && -f $path;
            $files{$path} = 1;
        }
    } else {
        print STDERR "Warning: No .fls record; checking all copied .tex files (unused files may be included).\n";
        $files{abs_path($_)} = 1 for tex_files($root);
    }
    $files{abs_path("$root/$entry")} = 1;
    my $total = 0;
    for my $file (sort keys %files) {
        my $number = 0;
        for my $raw (read_lines($file)) {
            ++$number;
            my $line = decode('UTF-8', $raw, FB_CROAK);
            my $code = code_only($line);
            next unless $code =~ /[\p{Hiragana}\p{Katakana}\p{Han}\x{3006}\x{30FC}\x{FF70}]/;
            print "Untranslated Japanese detected:\n" if $total++ == 0;
            $line =~ s/\r?\n\z//;
            my $relative = File::Spec->abs2rel($file, $root);
            print "  ", decode('UTF-8', $relative, FB_CROAK), ":$number\n    $line\n\n";
        }
    }
    print "Total: $total untranslated lines\n" if $total;
}

sub needs_bib {
    my ($file, $seen) = @_;
    return 0 if $seen->{$file}++;
    # Missing aux after a successful TeX command is a build error.
    for my $line (read_lines($file)) {
        return 1 if $line =~ /\\bibdata\{/;
        if ($line =~ /\\\@input\{([^}]+)\}/ && -f $1) {
            return 1 if needs_bib($1, $seen);
        }
    }
    return 0;
}

my ($action, @args) = @ARGV;
if ($action eq 'check-tree') {
    tex_files($args[0]);
} elsif ($action eq 'preprocess') {
    preprocess($_) for tex_files($args[0]);
} elsif ($action eq 'both') {
    my ($root, $entry) = @args;
    my $entry_path = abs_path("$root/$entry");
    die "Entry file not found: $entry\n" unless defined $entry_path && -f $entry_path;
    preprocess($_, 'both', abs_path($_) eq $entry_path) for tex_files($root);
} elsif ($action eq 'scan') {
    scan(@args);
} elsif ($action eq 'needs-bib') {
    exit(needs_bib($args[0], {}) ? 0 : 1);
} else {
    die "Unknown action: $action\n";
}
