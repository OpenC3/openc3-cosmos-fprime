# OpenC3 COSMOS FPrime Plugin

See the [OpenC3](https://openc3.com) documentation for all things OpenC3.

This plugin provides the code necessary to quickly get COSMOS talking with a FPrime based system.
Note that this plugin must be copied from source and configured for your specific FPrime system before installing.

This supports and has been tested against FPrime 3.6 and FPrime 4.2. It probably will work with other
versions as well.

Note that this plugin expects your topology should be setup as a TCP/IP Server so that COSMOS can connect to it.

## Getting Started

1. Locate the .json data dictionary from your FPrime project. It should be under the build-artifacts folder.
2. From the root folder of the plugin, run: python lib/fprime_parser.py FPRIME /path/to/your/Dictionary.json
3. Build the plugin: rake build VERSION=1.0.0

## Installing into OpenC3 COSMOS

1. Go to the OpenC3 Admin Tool, Plugins Tab
1. Click the install button and choose your plugin.gem file
1. Fill out plugin parameters
1. Click Install

## File Downlink and Data Products

Every file downlinked by the FPrime `FileDownlink` component (e.g. `SendFile`, or `DpCatalog` transmitting
data products) is reassembled and written to the COSMOS logs bucket at
`<SCOPE>/fprime_downlink/<TARGET>/<file name>`. Browse them with Bucket Explorer. The `FILE_START`,
`FILE_DATA`, `FILE_END` and `FILE_CANCEL` packets are also available as telemetry.

- Transfers with missing data are stored as `<file name>.incomplete`.
- Data product files (`.fdp`) are decoded using the `records` and `containers` in your dictionary. A
  `decoded/<file name>.json` with the decoded header and records is written under the same target folder,
  keeping generated JSON separate from downlinked files, and a `DP_HEADER`
  packet plus one `DP.<record name>` packet per record are emitted, timestamped with the container's time tag.
  `DP_HEADER` reports `HEADER_CRC_OK`, `DATA_CRC_OK` and `DECODE_OK`.
- Compressed data products (`DpCompressProc`, FPrime 4.4+) are decompressed before decoding.
- Array records whose elements are structs, enums or strings appear in telemetry as a raw `VALUE` block;
  the `.json` file has the decoded values.
- Re-run `fprime_parser.py` whenever your flight dictionary changes. Record definitions and framework type
  widths (notably `FwSizeStoreType`, which is U64 starting with FPrime 4.4) come from it.
- Files are reassembled in memory, up to 100 MiB by default. To change this, append the bucket folder and
  the size in bytes to the `fprime_file_downlink_protocol.py` lines in `plugin.txt`, e.g.
  `... <%= fprime_target_name %> fprime_downlink 524288000`.
  The same limit bounds the total decompressed record stream. Decoding a data product holds every value
  in memory too (roughly 10x the product size for large
  arrays), so keep very large products, such as images, to a few tens of MiB or lower `max_file_size`.
- FPrime 4 `CfdpManager` (true CFDP) transfers are not supported.

## Contributions

By submitting a Contribution, you agree to the following terms:

1. **Grant of License**: You hereby grant to OpenC3, Inc. a perpetual, irrevocable, worldwide, royalty-free, fully paid-up, non-exclusive, sublicensable, and transferable license to use, reproduce, prepare derivative works of, publicly display, publicly perform, distribute, sublicense, sell, and otherwise exploit your Contribution and any derivative works thereof, for any purpose whatsoever, without restriction or obligation to you.

2. **Grant of Patent License**: You hereby grant to OpenC3, Inc. a perpetual, irrevocable, worldwide, royalty-free, fully paid-up, non-exclusive, sublicensable, and transferable patent license to make, have made, use, offer to sell, sell, import, and otherwise transfer your Contribution, where such license applies only to those patent claims licensable by you that are necessarily infringed by your Contribution alone or by combination of your Contribution with the Software.

3. **Representation of Authority**: You represent that you are legally entitled to grant the above licenses. If your employer has rights to intellectual property you create, you represent that you have received permission to make the Contribution on behalf of your employer, or that your employer has waived such rights for your Contribution.

4. **Representation of Originality**: You represent that each Contribution is your original creation and that you have the right to grant the licenses herein. You will identify any third-party licenses or restrictions associated with any part of your Contribution.

5. **No Obligation**: You acknowledge that OpenC3, Inc. is under no obligation to accept, use, or include any Contribution.

6. **No Expectation of Compensation**: Contributions are provided voluntarily. You have no expectation of compensation, royalties, or other payment for any Contribution, regardless of how OpenC3, Inc. uses it.

Contributing is easy.

1. Fork the project
2. Create a feature branch
3. Make your changes
4. Submit a pull request

This protects both you and us and you retain full rights to any code you write.

## License

This OpenC3 plugin is released under the MIT License. See [LICENSE.txt](LICENSE.txt)
