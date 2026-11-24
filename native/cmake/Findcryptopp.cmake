# Homebrew and other system installs of Crypto++ do not always ship a
# CMake package. wfslib asks for cryptopp::cryptopp.
find_path(CRYPTOPP_INCLUDE_DIR NAMES cryptopp/cryptlib.h)
find_library(CRYPTOPP_LIBRARY NAMES cryptopp libcryptopp)
include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(
    cryptopp
    REQUIRED_VARS CRYPTOPP_LIBRARY CRYPTOPP_INCLUDE_DIR
)
if(cryptopp_FOUND AND NOT TARGET cryptopp::cryptopp)
    add_library(cryptopp::cryptopp UNKNOWN IMPORTED GLOBAL)
    set_target_properties(cryptopp::cryptopp PROPERTIES
        IMPORTED_LOCATION "${CRYPTOPP_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${CRYPTOPP_INCLUDE_DIR}"
    )
endif()
mark_as_advanced(CRYPTOPP_INCLUDE_DIR CRYPTOPP_LIBRARY)
