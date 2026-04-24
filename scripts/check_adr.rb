#!/usr/bin/env ruby

require 'json'
require 'pathname'
require 'time'

ROOT = Pathname(__dir__).join('..').expand_path
ADR_DIR = ROOT.join('docs', 'adr')
REPORT_PATH = ROOT.join('reports', 'adr-check.json')
ADR_PATTERN = /^\d{4}-[a-z0-9-]+\.md$/
REQUIRED_HEADINGS = [
  '## Context',
  '## Decision',
  '## Consequences',
  '## Related Artifacts'
].freeze

def fail_with(errors)
  errors.each { |error| warn(error) }
  exit 1
end

errors = []
entries = []

unless ADR_DIR.directory?
  fail_with(["docs/adr directory does not exist"])
end

files = ADR_DIR.children.select(&:file?).sort
template_present = false
accepted_present = false

files.each do |path|
  basename = path.basename.to_s
  unless basename.match?(ADR_PATTERN)
    errors << "#{path.relative_path_from(ROOT)}: invalid ADR filename"
    next
  end

  text = path.read
  status_line = text.lines.find { |line| line.start_with?('Status: ') }
  errors << "#{path.relative_path_from(ROOT)}: missing Status line" unless status_line

  missing_headings = REQUIRED_HEADINGS.reject { |heading| text.include?(heading) }
  unless missing_headings.empty?
    errors << "#{path.relative_path_from(ROOT)}: missing headings #{missing_headings.join(', ')}"
  end

  status = status_line ? status_line.sub('Status: ', '').strip : nil
  template_present ||= basename == '0000-adr-template.md'
  accepted_present ||= (basename != '0000-adr-template.md' && status && status != 'template')

  entries << {
    'path' => path.relative_path_from(ROOT).to_s,
    'status' => status,
    'missing_headings' => missing_headings
  }
end

errors << 'docs/adr/0000-adr-template.md is missing' unless template_present
errors << 'At least one non-template ADR is required' unless accepted_present

fail_with(errors) unless errors.empty?

report = {
  'generated_at' => Time.now.utc.iso8601,
  'tool' => 'scripts/check_adr.rb',
  'adr_directory' => 'docs/adr',
  'entries' => entries
}

REPORT_PATH.dirname.mkpath unless REPORT_PATH.dirname.exist?
REPORT_PATH.write(JSON.pretty_generate(report) + "\n")

puts("ADR structure checks passed for #{entries.length} file(s)")
puts("Wrote report #{REPORT_PATH.relative_path_from(ROOT)}")
