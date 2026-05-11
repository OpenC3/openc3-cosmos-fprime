# OpenC3 COSMOS FPrime Plugin

See the [OpenC3](https://openc3.com) documentation for all things OpenC3.

This plugin provides the code necessary to quickly get COSMOS talking with an FPrime based system.
Note that this plugin must be copied from source and configured for your specific FPrime system before installing.

## Getting Started

1. Locate the .json data dictionary from your FPrime project. It should be under the build-artifacts folder.
2. From the root folder of the plugin, run: python lib/fprime_parser.py FPRIME /path/to/your/Dictionary.json
3. Build the plugin: rake build VERSION=1.0.0

## Installing into OpenC3 COSMOS

1. Go to the OpenC3 Admin Tool, Plugins Tab
1. Click the install button and choose your plugin.gem file
1. Fill out plugin parameters
1. Click Install

## Contributing

We encourage you to contribute to OpenC3!

Contributing is easy.

1. Fork the project
2. Create a feature branch
3. Make your changes
4. Submit a pull request

Before any contributions can be incorporated we do require all contributors to agree to a Contributor License Agreement

This protects both you and us and you retain full rights to any code you write.

## License

This OpenC3 plugin is released under the MIT License. See [LICENSE.txt](LICENSE.txt)
