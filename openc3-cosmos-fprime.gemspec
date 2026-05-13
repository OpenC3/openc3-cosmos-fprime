# encoding: ascii-8bit

# Create the overall gemspec
Gem::Specification.new do |s|
  s.name = 'openc3-cosmos-fprime'
  s.summary = 'OpenC3 COSMOS FPrime Plugin'
  s.description = <<-EOF
    Provides the necessary code generation to configure OpenC3 COSMOS for an FPrime based system.
  EOF
  s.license = 'MIT'
  s.authors = ['Ryan Melton']
  s.email = ['plugins@openc3.com']
  s.homepage = 'https://github.com/OpenC3/openc3-cosmos-fprime'
  s.platform = Gem::Platform::RUBY
  s.required_ruby_version = '>= 3.0'
  s.metadata = {
    'openc3_store_keywords' => 'FPrime',
    "openc3_store_title" => 'FPrime',
    'source_code_uri' => 'https://github.com/OpenC3/openc3-cosmos-fprime',
    'openc3_cosmos_minimum_version' => '7.1.1'
  }

  if ENV['VERSION']
    s.version = ENV['VERSION'].dup
  else
    time = Time.now.strftime("%Y%m%d%H%M%S")
    s.version = '0.0.0' + ".#{time}"
  end
  s.files = Dir.glob("{targets,lib,tools,microservices}/**/*") + %w(Rakefile README.md LICENSE.md plugin.txt requirements.txt)
end
