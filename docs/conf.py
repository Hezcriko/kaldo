# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/stable/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

# Incase the project was not installed
import os
import sys
sys.path.insert(0, os.path.abspath('..'))

# import kaldo


# -- Project information -----------------------------------------------------

project = 'kALDo'
copyright = ("2020, Giuseppe Barbalinardo, Zekun Chen, Nicholas W. Lundgren, Davide Donadio")
author = 'Giuseppe Barbalinardo, Zekun Chen, Nicholas W. Lundgren, Davide Donadio'

# The short X.Y version
version = ''
# The full version, including alpha/beta/rc tags
release = ''


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autosummary',
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx.ext.extlinks',
    'recommonmark',
    'nbsphinx',
    'numpydoc',
    'sphinx.ext.pngmath']


# We do it like this to support multiple sphinx version without having warning.
# Our buildbot consider warning as error.
try:
    from sphinx.ext import imgmath
    extensions.append('sphinx.ext.imgmath')
except ImportError:
    try:
        from sphinx.ext import pngmath
        extensions.append('sphinx.ext.pngmath')
    except ImportError:
        pass

autosummary_generate = True
napoleon_google_docstring = False
napoleon_use_param = True
napoleon_use_ivar = True

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix(es) of docsource filenames.
# You can specify multiple suffix as a list of string:
#
source_suffix = ['.rst', '.md', '.ipynb']
# source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to docsource directory, that match files and
# directories to ignore when looking for docsource files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns = ['_build',
                    'Thumbs.db',
                    '.DS_Store',
                    '**.ipynb_checkpoints']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'default'

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_material'

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
# html_theme_options = {'description':'kALDo, Anharmonic Lattice Dynamics',
#                       'github-repo':'https://github.com/nanotheorygroup/kaldo'}
# Material theme options (see theme.conf for more information)
html_theme_options = {

    # Set the name of the project to appear in the navigation.
    'nav_title': 'kALDo',

    # Set you GA account ID to enable tracking
    'google_analytics_account': 'UA-172053863-1',

    # Specify a base_url used to generate sitemap.xml. If not
    # specified, then no sitemap will be built.
    'base_url': 'https://github.com/nanotheorygroup/kaldo',

    # Set the color and the accent color
    'color_primary': 'red',
    'color_accent': 'orange',

    # Set the repo location to get a badge with stats
    'repo_url': 'https://github.com/nanotheorygroup/kaldo',
    'repo_name': 'kALDo',

    # Visible levels of the global TOC; -1 means unlimited
    'globaltoc_depth': 1,
    # If False, expand all TOC entries
    'globaltoc_collapse': True,
    # If True, show hidden TOC entries
    'globaltoc_includehidden': False,
    # 'nav_links':[{'href':'./',href
    #               'title': 'test_link'}]
}

html_sidebars = {
    "**": ["logo-text.html", "globaltoc.html", "localtoc.html", "searchbox.html"]
}
# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}


# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = 'kaldodoc'


# -- Options for LaTeX output ------------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',

    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',

    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',

    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (docsource start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'kaldo.tex', 'kaldo Documentation',
     'kaldo', 'manual'),
]


# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (docsource start file, name, description, authors, manual section).
man_pages = [
    (master_doc, 'kaldo', 'kaldo Documentation',
     [author], 1)
]


# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (docsource start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'kaldo', 'kaldo Documentation',
     author, 'kaldo', 'Anharmonic Lattice Dynamics',
     'Miscellaneous'),
]

nbsphinx_execute = 'never'

latex_engine = 'pdflatex'

# mathjax_config = {
#     'extensions': ['tex2jax.js'],
#     'jax': ['input/TeX', 'output/HTML-CSS'],
# }
default_role = 'math'
pngmath_divpng_args = ['-gamma 1.5','-D 110']
#pngmath_divpng_args = ['-gamma', '1.5', '-D', '110', '-bg', 'Transparent']
imgmath_latex_preamble =  '\\usepackage{amsmath}\n'+\
                          '\\usepackage{mathtools}\n'+\
                          '\\usepackage{amsfonts}\n'+\
                          '\\usepackage{amssymb}\n'+\
                          '\\usepackage{dsfont}\n'
