/*
 * Copyright (C) 2026 wfs-studio contributors
 *
 * This software may be modified and distributed under the terms
 * of the MIT license. See the LICENSE file for details.
 *
 * Opening an image and deriving the USB or MLC key follows koolkdev's
 * wfs-extract, which is MIT. This program writes meta/meta.xml and
 * meta/iconTex.tga from /usr/title.
 */

#include <wfslib/wfslib.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr uint32_t kMaxCatalogBytes = 8u * 1024u * 1024u;

struct Options {
  std::string input;
  std::string output;
  std::string type = "usb";
  std::optional<std::string> otp;
  std::optional<std::string> seeprom;
  bool recovery = false;
  bool help = false;
};

void say(const std::string& line) {
  std::cout << line << '\n';
  std::cout.flush();
}

void say_err(const std::string& line) {
  std::cerr << line << '\n';
  std::cerr.flush();
}

void print_help() {
  say("usage: wfs-catalog --input <image> --output <folder> [--type usb|mlc|plain]");
  say("                   [--otp <path>] [--seeprom <path>] [--dump-usr-dir]");
  say("");
  say("Reads /usr/title and writes meta/meta.xml and meta/iconTex.tga.");
  say("The input is opened read-only.");
}

bool take_value(int argc, char** argv, int& index, const char* flag, std::string& value, std::string& error) {
  if (index + 1 >= argc) {
    error = std::string("Missing value for ") + flag;
    return false;
  }
  index += 1;
  value = argv[index];
  if (value.empty()) {
    error = std::string("Missing value for ") + flag;
    return false;
  }
  return true;
}

bool parse_args(int argc, char** argv, Options& options, std::string& error) {
  for (int index = 1; index < argc; ++index) {
    const std::string arg = argv[index];
    if (arg == "--help" || arg == "-h") {
      options.help = true;
    } else if (arg == "--dump-usr-dir") {
      options.recovery = true;
    } else if (arg == "--verbose") {
      // Catalog always names the files it writes.
    } else if (arg == "--dump-path") {
      error = "Catalog reads /usr/title and does not take --dump-path";
      return false;
    } else if (arg == "--input") {
      if (!take_value(argc, argv, index, "--input", options.input, error))
        return false;
    } else if (arg == "--output") {
      if (!take_value(argc, argv, index, "--output", options.output, error))
        return false;
    } else if (arg == "--type") {
      if (!take_value(argc, argv, index, "--type", options.type, error))
        return false;
    } else if (arg == "--otp") {
      std::string value;
      if (!take_value(argc, argv, index, "--otp", value, error))
        return false;
      options.otp = value;
    } else if (arg == "--seeprom") {
      std::string value;
      if (!take_value(argc, argv, index, "--seeprom", value, error))
        return false;
      options.seeprom = value;
    } else {
      error = "Unknown option " + arg;
      return false;
    }
  }
  return true;
}

std::optional<std::vector<std::byte>> image_key(const Options& options) {
  if (options.type == "mlc") {
    if (!options.otp)
      throw std::runtime_error("missing otp");
    std::unique_ptr<OTP> otp(OTP::LoadFromFile(*options.otp));
    return otp->GetMLCKey();
  }
  if (options.type == "usb") {
    if (!options.otp || !options.seeprom)
      throw std::runtime_error("missing seeprom");
    std::unique_ptr<OTP> otp(OTP::LoadFromFile(*options.otp));
    std::unique_ptr<SEEPROM> seeprom(SEEPROM::LoadFromFile(*options.seeprom));
    return seeprom->GetUSBKey(*otp);
  }
  if (options.type == "plain")
    return std::nullopt;
  throw std::runtime_error("unexpected type");
}

bool is_hex8(const std::string& name) {
  if (name.size() != 8)
    return false;
  for (unsigned char character : name) {
    if (std::isxdigit(character) == 0)
      return false;
  }
  return true;
}

bool write_catalog_file(const std::shared_ptr<File>& file, const std::filesystem::path& dest) {
  const uint32_t size = file->Size();
  if (size > kMaxCatalogBytes) {
    say_err("Error: " + dest.generic_string() + " is larger than the catalog limit");
    return false;
  }
  std::filesystem::create_directories(dest.parent_path());
  std::ofstream output(dest, std::ios::binary | std::ios::out | std::ios::trunc);
  if (!output) {
    say_err("Error: Failed to create " + dest.generic_string());
    return false;
  }
  File::stream stream(file);
  std::array<char, 0x2000> data{};
  size_t left = size;
  while (left > 0) {
    const std::streamsize ask = static_cast<std::streamsize>(std::min(data.size(), left));
    stream.read(data.data(), ask);
    const std::streamsize got = stream.gcount();
    if (got <= 0) {
      output.close();
      std::filesystem::remove(dest);
      say_err("Error: Failed to read " + dest.filename().generic_string());
      return false;
    }
    output.write(data.data(), got);
    if (!output) {
      output.close();
      std::filesystem::remove(dest);
      say_err("Error: Failed to write " + dest.generic_string());
      return false;
    }
    left -= static_cast<size_t>(got);
  }
  output.close();
  if (output.fail()) {
    std::filesystem::remove(dest);
    say_err("Error: Failed to write " + dest.generic_string());
    return false;
  }
  return true;
}

std::shared_ptr<Directory> meta_directory(const std::shared_ptr<Directory>& title) {
  auto meta = title->GetDirectory("meta");
  if (!meta.has_value()) {
    if (meta.error() == WfsError::kItemNotFound)
      return nullptr;
    throw WfsException(meta.error());
  }
  return *meta;
}

// 1 when meta.xml was written, 0 when this folder is not a title, -1 on failure.
int catalog_title(const std::shared_ptr<Directory>& title,
                  const std::filesystem::path& output_root,
                  const std::string& wfs_dir) {
  try {
    auto meta = meta_directory(title);
    if (!meta)
      return 0;
    auto xml = meta->GetFile("meta.xml");
    if (!xml.has_value()) {
      if (xml.error() == WfsError::kItemNotFound)
        return 0;
      throw WfsException(xml.error());
    }
    const std::filesystem::path dest_dir = output_root / std::filesystem::path(wfs_dir) / "meta";
    const std::filesystem::path xml_dest = dest_dir / "meta.xml";
    say("Dumping /" + wfs_dir + "/meta/meta.xml");
    if (!write_catalog_file(*xml, xml_dest))
      return -1;
    auto icon = meta->GetFile("iconTex.tga");
    if (!icon.has_value()) {
      if (icon.error() != WfsError::kItemNotFound)
        throw WfsException(icon.error());
      return 1;
    }
    say("Dumping /" + wfs_dir + "/meta/iconTex.tga");
    if (!write_catalog_file(*icon, dest_dir / "iconTex.tga"))
      return -1;
    return 1;
  } catch (const WfsException& error) {
    say_err("Error: Failed to catalog /" + wfs_dir + " (" + error.what() + ")");
    return -1;
  } catch (const std::exception& error) {
    say_err("Error: Failed to catalog /" + wfs_dir + " (" + error.what() + ")");
    return -1;
  }
}

std::vector<std::pair<std::string, std::shared_ptr<Directory>>> hex_children(const std::shared_ptr<Directory>& dir,
                                                                             const std::string& parent,
                                                                             bool& failed) {
  std::vector<std::pair<std::string, std::shared_ptr<Directory>>> children;
  for (auto [name, item_or_error] : *dir) {
    try {
      auto item = throw_if_error(std::move(item_or_error));
      if (!item->is_directory() || !is_hex8(name))
        continue;
      auto child = std::dynamic_pointer_cast<Directory>(item);
      if (child)
        children.emplace_back(name, std::move(child));
    } catch (const WfsException& error) {
      failed = true;
      say_err("Error: Failed to read /" + parent + "/" + name + " (" + error.what() + ")");
    }
  }
  return children;
}

int catalog_tree(const std::shared_ptr<Directory>& titles, const std::filesystem::path& output) {
  bool failed = false;
  int count = 0;
  const auto highs = hex_children(titles, "usr/title", failed);
  for (const auto& [high, high_dir] : highs) {
    const std::string high_path = "usr/title/" + high;
    const int direct = catalog_title(high_dir, output, high_path);
    if (direct < 0) {
      failed = true;
      continue;
    }
    if (direct > 0) {
      count += 1;
      continue;
    }
    const auto lows = hex_children(high_dir, high_path, failed);
    for (const auto& [low, low_dir] : lows) {
      const int wrote = catalog_title(low_dir, output, high_path + "/" + low);
      if (wrote < 0)
        failed = true;
      else if (wrote > 0)
        count += 1;
    }
  }
  say("Titles: " + std::to_string(count));
  say("Done!");
  return failed ? 1 : 0;
}

std::shared_ptr<Directory> open_titles(const Options& options, std::shared_ptr<WfsDevice>& device_out) {
  auto key = image_key(options);
  auto device = std::make_shared<FileDevice>(options.input, 9, 0, true);
  if (options.recovery) {
    auto opened = Recovery::OpenUsrDirectoryWithoutWfsDeviceHeader(device, key);
    if (!opened.has_value()) {
      if (opened.error() == WfsError::kInvalidWfsVersion) {
        say_err(
            "Error: Didn't find directory at the expected location, either the /usr dir is also corrupted "
            "or the keys are wrong");
      } else {
        say_err(std::string("Error: ") + WfsException(opened.error()).what());
      }
      return nullptr;
    }
    device_out = *opened;
    return device_out->GetDirectory("title");
  }
  auto detection = Recovery::DetectDeviceParams(device, key);
  if (detection.has_value()) {
    if (*detection == WfsError::kInvalidWfsVersion)
      say_err("Error: Incorrect WFS version, possible wrong keys");
    else
      say_err(std::string("Error: ") + WfsException(*detection).what());
    return nullptr;
  }
  auto opened = WfsDevice::Open(device, key);
  if (!opened.has_value()) {
    say_err(std::string("Error: ") + WfsException(opened.error()).what());
    return nullptr;
  }
  device_out = *opened;
  return device_out->GetDirectory("usr/title");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    Options options;
    std::string error;
    if (!parse_args(argc, argv, options, error)) {
      say_err("Error: " + error);
      say_err("Use --help to display program options");
      return 1;
    }
    if (options.help) {
      print_help();
      return 0;
    }
    if (options.input.empty() || options.output.empty()) {
      say_err("Error: --input and --output are required");
      say_err("Use --help to display program options");
      return 1;
    }
    if (options.type != "usb" && options.type != "mlc" && options.type != "plain") {
      say_err("Error: Invalid input type (valid types: usb/mlc/plain)");
      return 1;
    }
    if (options.type != "plain" && !options.otp) {
      say_err("Error: Missing --otp");
      return 1;
    }
    if (options.type == "usb" && !options.seeprom) {
      say_err("Error: Missing --seeprom");
      return 1;
    }

    const std::filesystem::path output = std::filesystem::absolute(options.output);
    const std::filesystem::path input = std::filesystem::absolute(options.input);
    if (output == input) {
      say_err("Error: The output folder is the same path as the input.");
      return 1;
    }
    if (std::filesystem::exists(output) && !std::filesystem::is_directory(output)) {
      say_err("Error: The output path exists and is not a folder.");
      return 1;
    }

    say("Dumping...");
    std::shared_ptr<WfsDevice> device;
    auto titles = open_titles(options, device);
    if (!device)
      return 1;
    if (!titles) {
      say_err("Error: Didn't find directory /usr/title in wfs");
      return 1;
    }
    return catalog_tree(titles, output);
  } catch (const std::exception& error) {
    say_err(std::string("Error: ") + error.what());
    return 1;
  }
}
