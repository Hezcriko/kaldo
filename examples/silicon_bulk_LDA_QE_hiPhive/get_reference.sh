# get_reference.sh is used to 
# obtain reference calculations
# for example 3

# Fetch precalculated force constants folder from remote
wget http://sophe.ucdavis.edu/structures/reference/updated_example/silicon_bulk_LDA_QE_hiPhive.tar.gz
# Untar precalculated files and clean up 
tar xzvf silicon_bulk_LDA_QE_hiPhive.tar.gz
rm -rf silicon_bulk_LDA_QE_hiPhive.tar.gz
echo  "  "
echo "Reference calculation files are obtained."
